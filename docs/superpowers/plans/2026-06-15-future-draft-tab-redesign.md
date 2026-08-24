> _Historical doc — paths/names have changed. Repo is now `Code Apps/public-dynasty` (GitHub `tkeefe66/public-dynasty-app`), Railway project **shimmering-nature**, live at https://ffbdynasty.com. Ignore stale refs to `sleeper-dynasty` / `sleeper-trade-grader` / `web-production-f949`._

# Future & Draft Tab Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the owner "Future & Draft" tab into a verdict-first narrative (draft-skill verdict → needs → pick arsenal with a per-pick past-picks table that tracks each pick's Current/Lowest/Highest value career arc), and deep-link the Draft Ace KPI card to it via a `?tab=future` URL param.

**Architecture:** Per-pick draft results are resolved once at refresh time (pure engine functions) and persisted as `drafted_picks: list[dict]` on `ChainCacheEntry`. The owner-detail service groups them per owner/season into a new `draft_picks_by_season` response field. The frontend reads that to render the redesigned tab. Value extremes (lowest/highest) come from scanning the existing daily KTC snapshot history (May-2026-forward only — surfaced honestly in tooltips). Per-pick regular/playoff points use a new owner-tenure, phase-aware started-points tally (NOT trade grades — a drafted-and-kept player is never "received in a trade", so the spec's trade-grade source would show 0 for kept picks).

**Tech Stack:** Python 3 engine (`src/sleeper_dynasty/`, pytest), FastAPI backend (`api/`, Pydantic), Next.js 14 + Tailwind frontend (`web/`, vitest). Five-metric vocabulary: never show "KTC" in UI — it is "Value".

---

## Deviations from the spec (intentional, called out for reviewer)

1. **Reg/Playoff Pts source.** Spec §Computation says "filter `entry.grades` for trades where this player was received." That only works for picks later traded; a kept drafted player has no trade grade and would show 0. **This plan instead computes started points via a new owner-tenure, phase-aware tally** (`started_points_while_on_roster`) — same metric definition (started regular-season pts; started title-bracket pts) sourced from weekly roster membership. Mirrors `engine/trade_grader.py::_points_while_owned` minus its post-trade gate.
2. **`avg_slot_value` grouping.** Spec says "(season, round, tier)". For SIMPLE math (user's explicit ask), this plan groups by **(season, round)** only — the average current value of all picks in the same round that year. `Avg Pick Value = current_value − round_average`.
3. **`acquired_via_trade` derivation.** Spec suggests cross-referencing `traded_picks`, but Sleeper drops used picks from `traded_picks`, so historical picks aren't reliably there. **This plan derives it from `resolved_trades`**: a pick is "via trade" if the drafter received that pick/player in any resolved trade (matched by `drafted_player_id`, or a received player with `via_pick`).

---

## File Structure

**Engine (pure, unit-tested):**
- Modify `src/sleeper_dynasty/api/.../ktc_snapshot_store.py` → actually lives at `api/app/services/ktc_snapshot_store.py` (backend service, but pure I/O). Add `value_extremes()`.
- Create `src/sleeper_dynasty/engine/draft_results.py` — `started_points_while_on_roster()` + `build_drafted_pick_results()`. Pure, no I/O.
- Create `tests/test_draft_results.py`.
- Create `api/tests/test_ktc_snapshot_extremes.py` (snapshot store lives in `api/`).

**Backend:**
- Modify `api/app/services/chain_cache.py` — add `drafted_picks` field.
- Modify `api/app/services/grader.py` — resolve + persist `drafted_picks` at refresh.
- Modify `api/app/models/owner.py` — `DraftPickResult` model + `draft_picks_by_season` on `OwnerDetailResp`.
- Modify `api/app/services/owner_view.py` — group `entry.drafted_picks` per owner/season.

**Frontend:**
- Modify `web/lib/types.ts` — `DraftPickResult` + `draft_picks_by_season`.
- Modify `web/app/league/[id]/owner/[uid]/page.tsx` — read `?tab`.
- Modify `web/components/OwnerDeepDive.tsx` — accept `initialTab`.
- Modify `web/components/HeroStatsRow.tsx` — Draft Ace href `?tab=future`.
- Create `web/components/ownerdeepdive/PastPicksTable.tsx` — the sortable per-pick table.
- Rewrite `web/components/ownerdeepdive/FutureDraftTab.tsx` — verdict → needs → arsenal.

---

## Task 1: Snapshot value extremes (lowest/highest)

**Files:**
- Modify: `api/app/services/ktc_snapshot_store.py`
- Test: `api/tests/test_ktc_snapshot_extremes.py`

Scans every stored daily snapshot once and returns each player's min/max superflex value across history. Powers the Lowest/Highest career-arc columns. History only goes back to ~May 2026 (snapshots are written opportunistically on refresh) — so these are window extremes, surfaced honestly in the UI tooltips.

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_ktc_snapshot_extremes.py`:

```python
from datetime import date

from app.services.ktc_snapshot_store import KtcSnapshotStore
from sleeper_dynasty.models.player import KTCValue


def _v(name: str, sf: int) -> KTCValue:
    return KTCValue(name=name, normalized_name=name.lower(),
                    position="WR", superflex_value=sf)


def test_value_extremes_min_max_across_snapshots(tmp_path):
    store = KtcSnapshotStore(cache_dir=tmp_path)
    store.capture({"a": _v("Aida", 3000)}, date(2026, 5, 1))
    store.capture({"a": _v("Aida", 5000)}, date(2026, 5, 8))
    store.capture({"a": _v("Aida", 4200)}, date(2026, 5, 15))
    ext = store.value_extremes()
    assert ext["aida"] == (3000.0, 5000.0)


def test_value_extremes_empty_when_no_snapshots(tmp_path):
    store = KtcSnapshotStore(cache_dir=tmp_path)
    assert store.value_extremes() == {}


def test_value_extremes_ignores_none_values(tmp_path):
    store = KtcSnapshotStore(cache_dir=tmp_path)
    store.capture({"a": _v("Aida", 3000)}, date(2026, 5, 1))
    store.capture({"b": KTCValue(name="Bo", normalized_name="bo",
                                 position="RB", superflex_value=None)},
                  date(2026, 5, 8))
    ext = store.value_extremes()
    assert ext["aida"] == (3000.0, 3000.0)
    assert "bo" not in ext
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && python -m pytest api/tests/test_ktc_snapshot_extremes.py -v`
Expected: FAIL with `AttributeError: 'KtcSnapshotStore' object has no attribute 'value_extremes'`

- [ ] **Step 3: Implement `value_extremes`**

In `api/app/services/ktc_snapshot_store.py`, add this method to the `KtcSnapshotStore` class (after `match`):

```python
    def value_extremes(self) -> dict[str, tuple[float, float]]:
        """Min/max superflex value per normalized name across ALL snapshots.

        Window-bounded: snapshots only exist from when capture began
        (~May 2026), so these are not true career extremes for older assets.
        Returns {normalized_name: (lowest, highest)}.
        """
        out: dict[str, tuple[float, float]] = {}
        for d in self.list_dates():
            snap = self._load(self._path(d))
            if not snap:
                continue
            for name, v in snap.items():
                if v.superflex_value is None:
                    continue
                val = float(v.superflex_value)
                lo, hi = out.get(name, (val, val))
                out[name] = (min(lo, val), max(hi, val))
        return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && python -m pytest api/tests/test_ktc_snapshot_extremes.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty"
git add api/app/services/ktc_snapshot_store.py api/tests/test_ktc_snapshot_extremes.py
git commit -m "feat(engine): KtcSnapshotStore.value_extremes — per-player min/max across snapshot history"
```

---

## Task 2: Owner-tenure phase-aware started-points tally

**Files:**
- Create: `src/sleeper_dynasty/engine/draft_results.py`
- Test: `tests/test_draft_results.py`

A drafted-and-kept player is never "received in a trade", so its regular/playoff points can't come from trade grades. This pure helper tallies a player's STARTED points while a given owner held them, gated by bracket phase — the same metric the dashboard uses, sourced from weekly roster membership. Mirrors `engine/trade_grader.py::_points_while_owned` (lines 218–252) minus the post-trade gate.

- [ ] **Step 1: Write the failing test**

Create `tests/test_draft_results.py`:

```python
from sleeper_dynasty.engine.draft_results import started_points_while_on_roster


def _matchups():
    # (league_id, week, roster_id) -> entry. Player "p1" on roster 1 (owner "U").
    return {
        ("L", 1, 1): {"starters": ["p1"], "players_points": {"p1": 10.0}},
        ("L", 2, 1): {"starters": ["p1"], "players_points": {"p1": 12.0}},
        # week 15 = playoff phase, p1 started:
        ("L", 15, 1): {"starters": ["p1"], "players_points": {"p1": 20.0}},
        # p1 on a DIFFERENT roster (owner sold him) — must not count:
        ("L", 3, 2): {"starters": ["p1"], "players_points": {"p1": 99.0}},
        # p1 benched (not in starters) — must not count for started tally:
        ("L", 4, 1): {"starters": [], "players_points": {"p1": 8.0}},
    }


_R2U = {"L": {1: "U", 2: "OTHER"}}
_PWS = {"L": 15}
_PHASE = {("L", 15, 1): "playoff"}


def test_regular_started_points_while_on_roster():
    pts = started_points_while_on_roster(
        "p1", "U", phase="regular", matchups=_matchups(),
        roster_to_user_by_league=_R2U,
        phase_by_lwr=_PHASE, playoff_week_start_by_league=_PWS)
    assert pts == 22.0  # weeks 1+2; not the sold-away 99, not the benched 8, not playoff


def test_playoff_started_points_while_on_roster():
    pts = started_points_while_on_roster(
        "p1", "U", phase="playoff", matchups=_matchups(),
        roster_to_user_by_league=_R2U,
        phase_by_lwr=_PHASE, playoff_week_start_by_league=_PWS)
    assert pts == 20.0  # week 15 only


def test_points_zero_for_owner_who_never_started_him():
    pts = started_points_while_on_roster(
        "p1", "OTHER", phase="regular", matchups=_matchups(),
        roster_to_user_by_league=_R2U,
        phase_by_lwr=_PHASE, playoff_week_start_by_league=_PWS)
    assert pts == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && python -m pytest tests/test_draft_results.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sleeper_dynasty.engine.draft_results'`

- [ ] **Step 3: Create the module with the tally**

Create `src/sleeper_dynasty/engine/draft_results.py`:

```python
"""Per-pick draft outcome results for the Future & Draft owner tab.

Pure functions: resolve each rookie-draft pick into a row carrying its career-arc
value (current/lowest/highest), value-vs-slot delta, how it was acquired, and the
started points it produced for the drafting owner. No I/O — callers thread in the
matchup/value/snapshot data already pulled during refresh.
"""

from __future__ import annotations

from sleeper_dynasty.engine.draft_signals import DraftedPick


def started_points_while_on_roster(
    pid: str,
    uid: str,
    *,
    phase: str,
    matchups: dict[tuple[str, int, int], dict],
    roster_to_user_by_league: dict[str, dict[int, str]],
    phase_by_lwr: dict[tuple[str, int, int], str] | None = None,
    playoff_week_start_by_league: dict[str, int] | None = None,
) -> float:
    """Started points ``pid`` scored for ``uid`` in weeks matching ``phase``.

    ``phase`` is "regular" (weeks before playoff start) or "playoff" (live
    title-bracket games per ``phase_by_lwr``). Owner-gated by weekly roster
    membership, so points after the owner trades the player away don't count.
    """
    phase_by_lwr = phase_by_lwr or {}
    playoff_week_start_by_league = playoff_week_start_by_league or {}
    total = 0.0
    for (lg, wk, rid), entry in matchups.items():
        if roster_to_user_by_league.get(lg, {}).get(rid) != uid:
            continue
        ps = playoff_week_start_by_league.get(lg, 15)
        wk_phase = "regular" if wk < ps else phase_by_lwr.get((lg, wk, rid), "dropped")
        if wk_phase != phase:
            continue
        if pid not in (entry.get("starters") or []):
            continue
        total += float((entry.get("players_points") or {}).get(pid, 0.0) or 0.0)
    return total
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && python -m pytest tests/test_draft_results.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty"
git add src/sleeper_dynasty/engine/draft_results.py tests/test_draft_results.py
git commit -m "feat(engine): started_points_while_on_roster — owner-tenure phase-aware started-points tally"
```

---

## Task 3: Build drafted-pick result rows

**Files:**
- Modify: `src/sleeper_dynasty/engine/draft_results.py`
- Test: `tests/test_draft_results.py`

Assemble the per-pick rows: current/lowest/highest value (career arc), `avg_slot_value` (round average) → drives the Avg Pick Value delta, `acquired_via_trade`, and started reg/playoff points. Returns plain dicts ready to serialize onto the cache entry.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_draft_results.py`:

```python
from sleeper_dynasty.engine.draft_results import build_drafted_pick_results
from sleeper_dynasty.engine.draft_signals import DraftedPick


def _pick(pid, drafter, rnd, slot, season=2025):
    return DraftedPick(draft_id="d", round=rnd, slot=slot, picks_in_round=12,
                       player_id=pid, drafter_id=drafter, draft_season=season)


def test_build_results_career_arc_and_avg_slot():
    picks = [
        _pick("p1", "U", rnd=1, slot=1),
        _pick("p2", "V", rnd=1, slot=2),
    ]
    rows = build_drafted_pick_results(
        picks,
        ktc_floats={"p1": 5000.0, "p2": 3000.0},
        normalized_name_by_pid={"p1": "aida", "p2": "bo"},
        names={"p1": "Aida", "p2": "Bo"},
        positions={"p1": "WR", "p2": "RB"},
        extremes_by_name={"aida": (3000.0, 6000.0)},  # p2 has no history
        acquired_set={("V", "p2")},                    # V got p2 via trade
        points_fn=lambda pid, uid, phase: {"p1": 100.0, "p2": 50.0}[pid]
        if phase == "regular" else 0.0,
    )
    by_pid = {r["player_id"]: r for r in rows}
    p1 = by_pid["p1"]
    assert p1["current_value"] == 5000.0
    assert p1["lowest_value"] == 3000.0
    assert p1["highest_value"] == 6000.0
    # round avg = (5000 + 3000) / 2 = 4000; p1 delta = +1000
    assert p1["avg_slot_value"] == 4000.0
    assert p1["acquired_via_trade"] is False
    assert p1["production_regular"] == 100.0
    assert p1["production_playoff"] == 0.0
    p2 = by_pid["p2"]
    # no snapshot history -> low=high=current
    assert p2["lowest_value"] == 3000.0
    assert p2["highest_value"] == 3000.0
    assert p2["acquired_via_trade"] is True


def test_build_results_folds_current_into_extremes():
    # current below the snapshot low, or above the high -> extremes widen to include it
    picks = [_pick("p1", "U", rnd=1, slot=1)]
    rows = build_drafted_pick_results(
        picks, ktc_floats={"p1": 2000.0},
        normalized_name_by_pid={"p1": "aida"}, names={"p1": "Aida"},
        positions={"p1": "WR"}, extremes_by_name={"aida": (3000.0, 6000.0)},
        acquired_set=set(), points_fn=lambda pid, uid, phase: 0.0)
    assert rows[0]["lowest_value"] == 2000.0   # current 2000 < snapshot low 3000
    assert rows[0]["highest_value"] == 6000.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && python -m pytest tests/test_draft_results.py -k build_results -v`
Expected: FAIL with `ImportError: cannot import name 'build_drafted_pick_results'`

- [ ] **Step 3: Implement `build_drafted_pick_results`**

Append to `src/sleeper_dynasty/engine/draft_results.py`:

```python
from collections import defaultdict
from typing import Callable


def build_drafted_pick_results(
    picks: list[DraftedPick],
    *,
    ktc_floats: dict[str, float],
    normalized_name_by_pid: dict[str, str],
    names: dict[str, str],
    positions: dict[str, str],
    extremes_by_name: dict[str, tuple[float, float]],
    acquired_set: set[tuple[str, str]],
    points_fn: Callable[[str, str, str], float],
) -> list[dict]:
    """One result dict per rookie-draft pick.

    Args:
        ktc_floats: player_id -> current superflex value.
        normalized_name_by_pid: player_id -> KTC normalized_name (snapshot key).
        names / positions: player_id -> display name / position.
        extremes_by_name: normalized_name -> (lowest, highest) from snapshots.
        acquired_set: {(drafter_uid, player_id)} the drafter got via a trade.
        points_fn: (player_id, uid, phase) -> started points; phase in
            {"regular", "playoff"}.
    """
    # Round averages of current value, per (season, round).
    groups: dict[tuple[int, int], list[float]] = defaultdict(list)
    for p in picks:
        groups[(p.draft_season, p.round)].append(ktc_floats.get(p.player_id, 0.0))
    avg_by_group = {
        k: (sum(vals) / len(vals)) if vals else 0.0 for k, vals in groups.items()
    }

    out: list[dict] = []
    for p in picks:
        cur = ktc_floats.get(p.player_id, 0.0)
        nn = normalized_name_by_pid.get(p.player_id)
        lo, hi = extremes_by_name.get(nn, (cur, cur)) if nn else (cur, cur)
        lo, hi = min(lo, cur), max(hi, cur)  # current always inside the arc
        out.append({
            "player_id": p.player_id,
            "full_name": names.get(p.player_id, p.player_id),
            "position": positions.get(p.player_id, ""),
            "drafter_id": p.drafter_id,
            "round": p.round,
            "slot": p.slot,
            "picks_in_round": p.picks_in_round,
            "draft_season": p.draft_season,
            "acquired_via_trade": (p.drafter_id, p.player_id) in acquired_set,
            "current_value": cur,
            "lowest_value": lo,
            "highest_value": hi,
            "avg_slot_value": avg_by_group.get((p.draft_season, p.round), 0.0),
            "production_regular": points_fn(p.player_id, p.drafter_id, "regular"),
            "production_playoff": points_fn(p.player_id, p.drafter_id, "playoff"),
        })
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && python -m pytest tests/test_draft_results.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty"
git add src/sleeper_dynasty/engine/draft_results.py tests/test_draft_results.py
git commit -m "feat(engine): build_drafted_pick_results — career-arc value + avg-slot delta + points per pick"
```

---

## Task 4: Persist `drafted_picks` on the cache entry

**Files:**
- Modify: `api/app/services/chain_cache.py:56`

Add the storage field. Backward-compatible via `default_factory=list` — pre-feature caches load with an empty list (the schema-version gate already forces a re-grade for stale caches, and refresh repopulates it). No `SCHEMA_VERSION` bump (consistent with how `season_records`, `draft_skill_by_season` were added).

- [ ] **Step 1: Add the field**

In `api/app/services/chain_cache.py`, immediately after the `season_records` field (line 56) and before `schema_version`:

```python
    # Per-pick rookie-draft results for the Future & Draft tab (one dict per pick;
    # keys per engine/draft_results.build_drafted_pick_results). Includes drafter_id
    # so owner_view can group per owner. Empty on pre-feature caches.
    drafted_picks: list[dict] = field(default_factory=list)
```

- [ ] **Step 2: Verify it loads**

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && python -c "from api.app.services.chain_cache import ChainCacheEntry; import dataclasses; print('drafted_picks' in {f.name for f in dataclasses.fields(ChainCacheEntry)})"`

Expected: `True`

(Note: if the import path fails, run from `api/` with `PYTHONPATH` per the repo's pytest config — the existing test suite import style is the source of truth.)

- [ ] **Step 3: Commit**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty"
git add api/app/services/chain_cache.py
git commit -m "feat(cache): add drafted_picks field to ChainCacheEntry"
```

---

## Task 5: Resolve `drafted_picks` during refresh

**Files:**
- Modify: `api/app/services/grader.py` (after the `compute_rating_signals` block, ~line 302; and the `ChainCacheEntry(...)` construction, ~line 358–380)

Wire the engine builders into the refresh. All inputs are already in scope at this point in `run()`: `rookie_picks`, `resolved_dicts`, `supporting[...]`, `snapshot_store`, `player_names` (local, line 102).

- [ ] **Step 1: Add the resolution block**

In `api/app/services/grader.py`, immediately AFTER the `compute_rating_signals` try/except (the block ending at line 302, right before the `# --- Dynasty outlooks` comment at line 304), insert:

```python
        # --- Per-pick draft results for the Future & Draft tab. ---
        drafted_picks: list[dict] = []
        try:
            from sleeper_dynasty.engine.draft_results import (
                build_drafted_pick_results, started_points_while_on_roster,
            )
            ktc_now = supporting["ktc_by_player_id"]
            ktc_floats_dp = {
                pid: float(v.superflex_value)
                for pid, v in ktc_now.items()
                if v is not None and v.superflex_value is not None
            }
            normalized_name_by_pid = {
                pid: v.normalized_name for pid, v in ktc_now.items() if v is not None
            }
            positions_dp = supporting.get("positions") or {}
            extremes = (
                snapshot_store.value_extremes() if snapshot_store is not None else {}
            )
            # A pick is "via trade" if the drafter received it (or the player it
            # became) in any resolved trade.
            acquired_set: set[tuple[str, str]] = set()
            for rt in resolved_dicts:
                for uid, side in (rt.get("sides") or {}).items():
                    for a in (side.get("received") or []):
                        if a.get("kind") == "pick" and a.get("drafted_player_id"):
                            acquired_set.add((uid, a["drafted_player_id"]))
                        elif a.get("kind") == "player" and a.get("via_pick"):
                            acquired_set.add((uid, a["player_id"]))

            def _points(pid: str, uid: str, phase: str) -> float:
                return started_points_while_on_roster(
                    pid, uid, phase=phase,
                    matchups=supporting["matchups"],
                    roster_to_user_by_league=supporting["roster_to_user_by_league"],
                    phase_by_lwr=supporting["phase_by_lwr"],
                    playoff_week_start_by_league=supporting["playoff_week_start_by_league"],
                )

            drafted_picks = build_drafted_pick_results(
                rookie_picks,
                ktc_floats=ktc_floats_dp,
                normalized_name_by_pid=normalized_name_by_pid,
                names=player_names,
                positions=positions_dp,
                extremes_by_name=extremes,
                acquired_set=acquired_set,
                points_fn=_points,
            )
        except Exception:
            log.exception("drafted-pick results computation skipped")
```

- [ ] **Step 2: Pass it into the cache entry**

In the `entry = ChainCacheEntry(...)` construction (line 358), add `drafted_picks=drafted_picks,` after the `roster_ranks=roster_ranks,` line (line 379):

```python
            dynasty_outlooks=dynasty_outlooks,
            roster_ranks=roster_ranks,
            drafted_picks=drafted_picks,
        )
```

- [ ] **Step 3: Verify the engine + existing suites still pass**

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && python -m pytest tests/test_draft_results.py api/tests/test_ktc_snapshot_extremes.py -v`
Expected: PASS (all)

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && python -m pytest api/tests -q`
Expected: PASS (no regressions; pre-existing unrelated `test_settings_llm_cost.py` failures, if any, are out of scope)

- [ ] **Step 4: Commit**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty"
git add api/app/services/grader.py
git commit -m "feat(refresh): resolve and persist per-pick drafted_picks results"
```

---

## Task 6: `DraftPickResult` model + `draft_picks_by_season` response field

**Files:**
- Modify: `api/app/models/owner.py` (add model near line 93; add field at line 108)
- Test: `api/tests/test_owner_draft_picks.py`

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_owner_draft_picks.py`:

```python
from app.models.owner import DraftPickResult, OwnerDetailResp


def test_draft_pick_result_shape():
    r = DraftPickResult(
        player_id="p1", full_name="Aida", position="WR", round=1, slot=1,
        picks_in_round=12, draft_season=2025, acquired_via_trade=False,
        current_value=5000.0, lowest_value=3000.0, highest_value=6000.0,
        avg_slot_value=4000.0, production_regular=100.0, production_playoff=0.0)
    assert r.current_value == 5000.0
    assert r.draft_season == 2025


def test_owner_detail_defaults_draft_picks_empty():
    d = OwnerDetailResp(
        league_id="L", user_id="U",
        owner={"user_id": "U", "owner_name": "Tom"},
        totals_by_lens={}, career_arc=[], best_trade_id=None, worst_trade_id=None)
    assert d.draft_picks_by_season == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && python -m pytest api/tests/test_owner_draft_picks.py -v`
Expected: FAIL with `ImportError: cannot import name 'DraftPickResult'`

- [ ] **Step 3: Add the model + field**

In `api/app/models/owner.py`, add after the `DraftSkillView` class (line 93):

```python
class DraftPickResult(BaseModel):
    player_id: str
    full_name: str
    position: str
    round: int
    slot: int
    picks_in_round: int
    draft_season: int
    acquired_via_trade: bool
    current_value: float
    lowest_value: float
    highest_value: float
    avg_slot_value: float
    production_regular: float
    production_playoff: float
```

Then in `OwnerDetailResp` (line 96), add after `franchise_blurb` (line 108):

```python
    franchise_blurb: str | None = None
    # str(season) -> picks the owner drafted that season (Future & Draft tab).
    draft_picks_by_season: dict[str, list[DraftPickResult]] = {}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && python -m pytest api/tests/test_owner_draft_picks.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty"
git add api/app/models/owner.py api/tests/test_owner_draft_picks.py
git commit -m "feat(api): DraftPickResult model + draft_picks_by_season on OwnerDetailResp"
```

---

## Task 7: Group drafted picks per owner/season in owner_view

**Files:**
- Modify: `api/app/services/owner_view.py` (import line 3–6; build block before `return`; the `OwnerDetailResp(...)` return at line 152)
- Test: `api/tests/test_owner_view_draft_picks.py`

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_owner_view_draft_picks.py`:

```python
from app.services.chain_cache import ChainCacheEntry
from app.services.owner_view import build_owner_detail


def _entry_with_picks():
    pick = {
        "player_id": "p1", "full_name": "Aida", "position": "WR",
        "drafter_id": "U", "round": 1, "slot": 1, "picks_in_round": 12,
        "draft_season": 2025, "acquired_via_trade": False,
        "current_value": 5000.0, "lowest_value": 3000.0, "highest_value": 6000.0,
        "avg_slot_value": 4000.0, "production_regular": 100.0,
        "production_playoff": 0.0,
    }
    other = {**pick, "player_id": "p9", "drafter_id": "OTHER"}
    return ChainCacheEntry(
        league_id="L", chain=[], resolved_trades=[], grades={},
        owners={"U": {"user_id": "U", "display_name": "Tom"}},
        playoff_weeks_by_league={}, roster_to_user_by_league={},
        league_name_by_id={}, league_season_by_id={},
        cached_at="2026-06-15T00:00:00Z",
        drafted_picks=[pick, other])


def test_draft_picks_grouped_by_season_for_owner_only():
    detail = build_owner_detail(_entry_with_picks(), "U")
    assert detail is not None
    assert set(detail.draft_picks_by_season) == {"2025"}
    rows = detail.draft_picks_by_season["2025"]
    assert len(rows) == 1                      # OTHER's pick excluded
    assert rows[0].player_id == "p1"
    assert rows[0].current_value == 5000.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && python -m pytest api/tests/test_owner_view_draft_picks.py -v`
Expected: FAIL (`draft_picks_by_season` empty — assertion `set(...) == {"2025"}` fails)

- [ ] **Step 3: Implement the grouping**

In `api/app/services/owner_view.py`, add `DraftPickResult` to the imports (line 3–6 block):

```python
from app.models.owner import (
    AgeProfileView, DraftCapitalView, DraftNeedView, DraftPickResult,
    DraftSkillView, OutlookView, OwnerDetailResp, OwnerTradeRow, PlayerLite,
    RankView, SeasonArc,
)
```

Then, immediately before the `return OwnerDetailResp(` at line 152, add:

```python
    # --- Drafted picks grouped per season (Future & Draft tab). ---
    draft_picks_by_season: dict[str, list[DraftPickResult]] = {}
    for p in (entry.drafted_picks or []):
        if p.get("drafter_id") != user_id:
            continue
        season = str(p.get("draft_season"))
        draft_picks_by_season.setdefault(season, []).append(DraftPickResult(
            player_id=p["player_id"], full_name=p["full_name"],
            position=p.get("position", ""), round=p["round"], slot=p["slot"],
            picks_in_round=p["picks_in_round"], draft_season=p["draft_season"],
            acquired_via_trade=bool(p.get("acquired_via_trade")),
            current_value=float(p.get("current_value", 0.0)),
            lowest_value=float(p.get("lowest_value", 0.0)),
            highest_value=float(p.get("highest_value", 0.0)),
            avg_slot_value=float(p.get("avg_slot_value", 0.0)),
            production_regular=float(p.get("production_regular", 0.0)),
            production_playoff=float(p.get("production_playoff", 0.0)),
        ))
    # Sort each season's rows by Avg Pick Value delta (best first).
    for rows_ in draft_picks_by_season.values():
        rows_.sort(key=lambda r: r.current_value - r.avg_slot_value, reverse=True)
```

Then add the field to the `OwnerDetailResp(...)` return (after `franchise_blurb=franchise_blurb,` at line 166):

```python
        franchise_blurb=franchise_blurb,
        draft_picks_by_season=draft_picks_by_season,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && python -m pytest api/tests/test_owner_view_draft_picks.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty"
git add api/app/services/owner_view.py api/tests/test_owner_view_draft_picks.py
git commit -m "feat(api): group drafted_picks per owner/season in build_owner_detail"
```

---

## Task 8: Frontend types

**Files:**
- Modify: `web/lib/types.ts:215` (after `DraftSkillView`) and `:231` (inside `OwnerDetailResp`)

- [ ] **Step 1: Add `DraftPickResult` interface**

In `web/lib/types.ts`, after line 215 (`export interface DraftSkillView ...`):

```typescript
export interface DraftPickResult {
  player_id: string;
  full_name: string;
  position: string;
  round: number;
  slot: number;
  picks_in_round: number;
  draft_season: number;
  acquired_via_trade: boolean;
  current_value: number;
  lowest_value: number;
  highest_value: number;
  avg_slot_value: number;
  production_regular: number;
  production_playoff: number;
}
```

- [ ] **Step 2: Add field to `OwnerDetailResp`**

In the `OwnerDetailResp` interface, after `franchise_blurb?: string | null;` (line 231):

```typescript
  franchise_blurb?: string | null;
  draft_picks_by_season?: Record<string, DraftPickResult[]>;
}
```

- [ ] **Step 3: Verify it typechecks**

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/web" && npx tsc --noEmit`
Expected: no errors

- [ ] **Step 4: Commit**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty"
git add web/lib/types.ts
git commit -m "feat(web): DraftPickResult type + draft_picks_by_season on OwnerDetailResp"
```

---

## Task 9: URL-based tab navigation (`?tab=`)

**Files:**
- Modify: `web/components/OwnerDeepDive.tsx:26-30` (accept `initialTab`)
- Modify: `web/app/league/[id]/owner/[uid]/page.tsx:22-26,56` (read `searchParams`, pass through)

- [ ] **Step 1: Accept `initialTab` in OwnerDeepDive**

In `web/components/OwnerDeepDive.tsx`, add `initialTab` to `Props` (after `onProfilesChange` at line 23):

```typescript
  onProfilesChange?: (profiles: ProfilesMap) => void;
  /** Deep-link entry tab (from the page's ?tab= param). */
  initialTab?: TabKey;
}
```

Add `TabKey` to the type import from OverviewTab (line 9 already imports `TabKey`). Then update the destructure (line 26–28) and the `useState` (line 30):

```typescript
export function OwnerDeepDive({
  leagueId, detail, standing, totalOwners, profile, others, onProfilesChange,
  initialTab,
}: Props) {
  const [editing, setEditing] = useState(false);
  const [tab, setTab] = useState<TabKey>(initialTab ?? "overview");
```

- [ ] **Step 2: Read `?tab` in the owner page and pass it**

In `web/app/league/[id]/owner/[uid]/page.tsx`, update the signature (line 22–26):

```typescript
export default async function OwnerPage({
  params,
  searchParams,
}: {
  params: { id: string; uid: string };
  searchParams?: { tab?: string };
}) {
```

Then add a validated tab just before the `return (` at line 43:

```typescript
  const VALID_TABS = ["overview", "roster", "future", "trades"] as const;
  const initialTab = (VALID_TABS as readonly string[]).includes(searchParams?.tab ?? "")
    ? (searchParams!.tab as (typeof VALID_TABS)[number])
    : "overview";
```

And pass it to the component (line 56):

```typescript
          <OwnerDeepDive leagueId={params.id} detail={data} initialTab={initialTab} />
```

- [ ] **Step 3: Verify it typechecks**

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/web" && npx tsc --noEmit`
Expected: no errors

- [ ] **Step 4: Commit**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty"
git add web/components/OwnerDeepDive.tsx "web/app/league/[id]/owner/[uid]/page.tsx"
git commit -m "feat(web): URL ?tab= deep-link support on owner page"
```

---

## Task 10: Draft Ace KPI card deep-links to the tab

**Files:**
- Modify: `web/components/HeroStatsRow.tsx:71`

- [ ] **Step 1: Point the Draft Ace card at `?tab=future`**

In `web/components/HeroStatsRow.tsx`, change the Draft Ace card's `href` (line 71) from:

```typescript
        href={ownerHref(draft_ace.owner_user_id)}
```

to:

```typescript
        href={draft_ace.owner_user_id
          ? `${ownerHref(draft_ace.owner_user_id)}?tab=future`
          : undefined}
```

- [ ] **Step 2: Verify it typechecks**

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/web" && npx tsc --noEmit`
Expected: no errors

- [ ] **Step 3: Commit**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty"
git add web/components/HeroStatsRow.tsx
git commit -m "feat(web): Draft Ace KPI card deep-links to ?tab=future"
```

---

## Task 11: Past-picks table component

**Files:**
- Create: `web/components/ownerdeepdive/PastPicksTable.tsx`
- Test: `web/components/ownerdeepdive/PastPicksTable.test.tsx`

The sortable per-pick table with year tabs (default = most recent season), Current/Lowest/Highest career-arc columns, Avg Pick Value +/− delta, and Reg/Playoff points. Tooltips on every column from Current rightward (via the existing `InfoTooltip` with `align="right"`). Styling follows `TradeStatTable.tsx` conventions (font-mono headers, `text-pos`/`text-neg`, `toLocaleString`).

- [ ] **Step 1: Write the failing test**

Create `web/components/ownerdeepdive/PastPicksTable.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PastPicksTable } from "./PastPicksTable";
import type { DraftPickResult } from "@/lib/types";

function pick(over: Partial<DraftPickResult> = {}): DraftPickResult {
  return {
    player_id: "p1", full_name: "Aida", position: "WR", round: 1, slot: 1,
    picks_in_round: 12, draft_season: 2025, acquired_via_trade: false,
    current_value: 5000, lowest_value: 3000, highest_value: 6000,
    avg_slot_value: 4000, production_regular: 100, production_playoff: 20,
    ...over,
  };
}

describe("PastPicksTable", () => {
  it("renders the most recent season's picks by default", () => {
    render(<PastPicksTable bySeason={{
      "2024": [pick({ draft_season: 2024, full_name: "Older" })],
      "2025": [pick({ full_name: "Aida" })],
    }} />);
    expect(screen.getByText("Aida")).toBeInTheDocument();
    expect(screen.queryByText("Older")).not.toBeInTheDocument();
  });

  it("shows +delta for a pick above its round average", () => {
    render(<PastPicksTable bySeason={{ "2025": [pick()] }} />);
    expect(screen.getByText("+1,000")).toBeInTheDocument(); // 5000 - 4000
  });

  it("labels acquisition as Owned or via trade", () => {
    render(<PastPicksTable bySeason={{
      "2025": [pick({ acquired_via_trade: true })],
    }} />);
    expect(screen.getByText(/via trade/i)).toBeInTheDocument();
  });

  it("renders empty state when no picks", () => {
    render(<PastPicksTable bySeason={{}} />);
    expect(screen.getByText(/no completed rookie drafts/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/web" && npx vitest run components/ownerdeepdive/PastPicksTable.test.tsx`
Expected: FAIL (cannot resolve `./PastPicksTable`)

- [ ] **Step 3: Implement the component**

Create `web/components/ownerdeepdive/PastPicksTable.tsx`:

```tsx
"use client";

import { useState } from "react";
import type { DraftPickResult } from "@/lib/types";
import { InfoTooltip } from "@/components/InfoTooltip";

const ord = (r: number): string =>
  ({ 1: "1st", 2: "2nd", 3: "3rd" } as Record<number, string>)[r] ?? `${r}th`;

const val = (n: number): string => Math.round(n).toLocaleString();
const pts = (n: number): string => n.toFixed(1);

function Delta({ n }: { n: number }) {
  const r = Math.round(n);
  const tone = r > 0 ? "text-pos" : r < 0 ? "text-neg" : "text-dim";
  const sign = r > 0 ? "+" : "";
  return <span className={tone}>{`${sign}${r.toLocaleString()}`}</span>;
}

const numTh = "text-right font-normal px-1 pb-1.5";
const numTd = "text-right tabular px-1 py-1.5";

export function PastPicksTable({ bySeason }: { bySeason: Record<string, DraftPickResult[]> }) {
  const seasons = Object.keys(bySeason).sort().reverse(); // most recent first
  const [active, setActive] = useState<string>(seasons[0] ?? "");

  if (seasons.length === 0) {
    return <div className="text-dim text-[12px]">No completed rookie drafts yet.</div>;
  }

  const rows = bySeason[active] ?? [];

  return (
    <div>
      <div className="flex gap-1 mb-3">
        {seasons.map((s) => (
          <button key={s} type="button" onClick={() => setActive(s)}
            className={`font-mono text-[11px] px-2.5 py-1 rounded border transition-colors ${
              s === active
                ? "border-ink text-ink font-bold"
                : "border-divider text-dim hover:text-ink"}`}>
            {s}
          </button>
        ))}
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-[12px] min-w-[640px]">
          <thead>
            <tr className="font-mono text-[9px] uppercase tracking-wide text-dim">
              <th className="text-left font-normal pr-1 pb-1.5">Player</th>
              <th className="text-left font-normal px-1 pb-1.5">Rnd</th>
              <th className="text-left font-normal px-1 pb-1.5">Acquired</th>
              <th className={numTh}>
                Current <InfoTooltip title="Current Value" body="Today's dynasty market value." align="right" />
              </th>
              <th className={numTh}>
                Lowest <InfoTooltip title="Lowest Value" body="Lowest value this player has hit since we began tracking (May 2026). Shows where the arc bottomed out." align="right" />
              </th>
              <th className={numTh}>
                Highest <InfoTooltip title="Highest Value" body="Highest value this player has hit since we began tracking (May 2026). Shows the arc's peak." align="right" />
              </th>
              <th className={numTh}>
                Avg Pick Value <InfoTooltip title="Avg Pick Value" body="How much this pick is worth compared to what a player at this slot typically produces. Positive means the pick outperformed its draft position." align="right" />
              </th>
              <th className={numTh}>
                Reg Pts <InfoTooltip title="Regular Season Points" body="Started points in regular-season weeks while on this roster." align="right" />
              </th>
              <th className={numTh}>
                Playoff Pts <InfoTooltip title="Playoff Points" body="Started points in real title-bracket games only." align="right" />
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.player_id} className="border-t border-divider">
                <td className="text-left pr-1 py-1.5 font-semibold">
                  {r.full_name}
                  <span className="text-dim font-normal ml-1.5 font-mono text-[10px]">{r.position}</span>
                </td>
                <td className="text-left px-1 py-1.5 text-dim font-mono text-[10px]">{ord(r.round)}</td>
                <td className="text-left px-1 py-1.5 text-dim font-mono text-[10px]">
                  {r.acquired_via_trade ? "via trade" : "Owned"}
                </td>
                <td className={`${numTd} font-semibold`}>{val(r.current_value)}</td>
                <td className={`${numTd} text-dim`}>{val(r.lowest_value)}</td>
                <td className={`${numTd} text-dim`}>{val(r.highest_value)}</td>
                <td className={numTd}><Delta n={r.current_value - r.avg_slot_value} /></td>
                <td className={numTd}>{pts(r.production_regular)}</td>
                <td className={numTd}>{pts(r.production_playoff)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/web" && npx vitest run components/ownerdeepdive/PastPicksTable.test.tsx`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty"
git add web/components/ownerdeepdive/PastPicksTable.tsx web/components/ownerdeepdive/PastPicksTable.test.tsx
git commit -m "feat(web): PastPicksTable — career-arc value columns + avg-pick-value delta, year-tabbed"
```

---

## Task 12: Rewrite FutureDraftTab (verdict → needs → arsenal)

**Files:**
- Modify: `web/components/ownerdeepdive/FutureDraftTab.tsx` (full rewrite)
- Modify: `web/components/OwnerDeepDive.tsx:103` (pass `draftPicksBySeason`)
- Test: `web/components/ownerdeepdive/FutureDraftTab.test.tsx`

Section 1 = plain verdict (rank + one counting sentence derived from hits-vs-misses across the picks). Section 2 = draft needs (unchanged). Section 3 = arsenal: future picks (existing chip grid) then the `PastPicksTable`.

- [ ] **Step 1: Write the failing test**

Create `web/components/ownerdeepdive/FutureDraftTab.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { FutureDraftTab } from "./FutureDraftTab";
import type { DraftPickResult, DraftSkillView, OutlookView } from "@/lib/types";

const outlook: OutlookView = {
  window: "Competing now", trajectory: "Peaking",
  age_profile: { avg_age_by_position: {}, overall_avg_age: 25, aging_risks: [], core_young: [] },
  draft_capital: {
    picks_by_season: { "2026": 2 }, picks_by_season_round: { "2026-1": 1, "2026-2": 1 },
    net_vs_average: 1, status: "balanced", total_value: 1200,
  },
  draft_needs: [],
};

const draftSkill: DraftSkillView = { score: 0.4, rank: 3, of: 12 };

function pick(over: Partial<DraftPickResult> = {}): DraftPickResult {
  return {
    player_id: "p1", full_name: "Aida", position: "WR", round: 1, slot: 1,
    picks_in_round: 12, draft_season: 2025, acquired_via_trade: false,
    current_value: 5000, lowest_value: 3000, highest_value: 6000,
    avg_slot_value: 4000, production_regular: 100, production_playoff: 20, ...over,
  };
}

describe("FutureDraftTab", () => {
  it("leads with the draft-skill rank verdict", () => {
    render(<FutureDraftTab outlook={outlook} draftSkill={draftSkill}
      draftPicksBySeason={{ "2025": [pick()] }} />);
    expect(screen.getByText(/#3 of 12/i)).toBeInTheDocument();
  });

  it("states more hits than misses when majority beat their slot", () => {
    render(<FutureDraftTab outlook={outlook} draftSkill={draftSkill}
      draftPicksBySeason={{ "2025": [
        pick({ player_id: "a", current_value: 5000, avg_slot_value: 4000 }), // hit
        pick({ player_id: "b", current_value: 5000, avg_slot_value: 4000 }), // hit
        pick({ player_id: "c", current_value: 3000, avg_slot_value: 4000 }), // miss
      ] }} />);
    expect(screen.getByText(/more of your picks have outperformed/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/web" && npx vitest run components/ownerdeepdive/FutureDraftTab.test.tsx`
Expected: FAIL (`draftPicksBySeason` not a prop; verdict text absent)

- [ ] **Step 3: Rewrite the component**

Replace the entire contents of `web/components/ownerdeepdive/FutureDraftTab.tsx`:

```tsx
"use client";

import { DraftPickResult, DraftSkillView, OutlookView } from "@/lib/types";
import { Card, CardHead, Chip } from "./ui";
import { PastPicksTable } from "./PastPicksTable";

const URGENCY_TONE: Record<string, string> = { immediate: "text-neg", developing: "text-dim" };

function ord(r: number): string {
  return ({ 1: "1st", 2: "2nd", 3: "3rd" } as Record<number, string>)[r] ?? `${r}th`;
}

function roundsForSeason(byRound: Record<string, number>, season: string): { round: number; count: number }[] {
  const out: { round: number; count: number }[] = [];
  for (const [k, c] of Object.entries(byRound)) {
    const [s, r] = k.split("-");
    if (s === season) out.push({ round: Number(r), count: c });
  }
  return out.sort((a, b) => a.round - b.round);
}

/** Plain counting sentence: hits (beat slot avg) vs misses across all picks. */
function verdictSentence(bySeason: Record<string, DraftPickResult[]>): string {
  const all = Object.values(bySeason).flat();
  if (all.length === 0) return "Not enough draft history yet to judge.";
  const hits = all.filter((p) => p.current_value - p.avg_slot_value > 0).length;
  const misses = all.length - hits;
  // Strongest class = season with the most hits.
  let bestSeason = "";
  let bestHits = -1;
  for (const [s, rows] of Object.entries(bySeason)) {
    const h = rows.filter((p) => p.current_value - p.avg_slot_value > 0).length;
    if (h > bestHits) { bestHits = h; bestSeason = s; }
  }
  const tail = bestHits > 0 ? ` Your ${bestSeason} class was the strongest.` : "";
  if (hits > misses) {
    return `More of your picks have outperformed their draft slot than missed.${tail}`;
  }
  if (misses > hits) {
    return `More of your picks have underperformed their slot than exceeded it.${tail}`;
  }
  return `Your picks have split evenly between beating and missing their slot.${tail}`;
}

export function FutureDraftTab({
  outlook, draftSkill, draftPicksBySeason,
}: {
  outlook: OutlookView;
  draftSkill?: DraftSkillView | null;
  draftPicksBySeason?: Record<string, DraftPickResult[]>;
}) {
  const dc = outlook.draft_capital;
  const seasons = Object.keys(dc.picks_by_season).sort();
  const bySeason = draftPicksBySeason ?? {};

  return (
    <div className="space-y-3">
      {/* Section 1 — Draft-skill verdict (hero). */}
      <Card>
        <div className="font-mono text-[9px] uppercase tracking-widest text-dim">Draft skill</div>
        <div className="text-[26px] font-extrabold tracking-tight leading-tight mt-1">
          {draftSkill ? `#${draftSkill.rank} of ${draftSkill.of}` : "—"}
          <span className="text-dim font-mono text-[12px] font-normal ml-2">in the league</span>
        </div>
        <p className="text-dim text-[13px] mt-2 leading-relaxed">{verdictSentence(bySeason)}</p>
      </Card>

      {/* Section 2 — Draft needs (unchanged). */}
      <Card>
        <CardHead title="Draft needs" />
        {outlook.draft_needs.length === 0 ? (
          <div className="text-dim text-[12px]">No pressing needs.</div>
        ) : (
          <ul className="space-y-2.5">
            {outlook.draft_needs.map((n, i) => (
              <li key={`${n.position}-${i}`} className="flex items-baseline gap-2.5">
                <span className="font-bold text-[14px] w-8 shrink-0">{n.position}</span>
                <span className={`font-mono text-[9px] uppercase tracking-widest shrink-0 ${URGENCY_TONE[n.urgency] ?? "text-dim"}`}>{n.urgency}</span>
                <span className="text-dim text-[12px]">{n.reason}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>

      {/* Section 3 — Pick arsenal: future picks, then past-picks table. */}
      <Card>
        <CardHead title="Pick arsenal" right={<span className="font-mono text-[10px] text-dim">future picks</span>} />
        {seasons.length === 0 ? (
          <div className="text-dim text-[12px] mb-5">No future picks tracked.</div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-6">
            {seasons.map((s) => {
              const rounds = roundsForSeason(dc.picks_by_season_round, s);
              return (
                <div key={s} className="bg-bg border border-divider rounded-card p-4">
                  <div className="flex items-baseline justify-between">
                    <div className="font-mono text-[11px] text-dim">{s}</div>
                    <div className="tabular text-[22px] font-extrabold leading-none">{dc.picks_by_season[s]}</div>
                  </div>
                  <div className="flex flex-wrap gap-1.5 mt-3">
                    {rounds.length === 0 ? (
                      <span className="font-mono text-[10px] text-dim">—</span>
                    ) : (
                      rounds.map((r) => (
                        <Chip key={r.round} tone={r.round === 1 ? "text-pos" : "text-dim"}>
                          <span className="font-mono text-[10px]">{ord(r.round)}{r.count > 1 ? ` ×${r.count}` : ""}</span>
                        </Chip>
                      ))
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}

        <div className="font-mono text-[10px] uppercase tracking-widest text-dim mb-2">How past picks panned out</div>
        <PastPicksTable bySeason={bySeason} />
      </Card>
    </div>
  );
}
```

- [ ] **Step 4: Pass the new prop from OwnerDeepDive**

In `web/components/OwnerDeepDive.tsx`, update the render line (line 103):

```typescript
        {tab === "future" && detail.outlook && <FutureDraftTab outlook={detail.outlook} draftSkill={detail.draft_skill} draftPicksBySeason={detail.draft_picks_by_season} />}
```

- [ ] **Step 5: Run tests + typecheck**

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/web" && npx vitest run components/ownerdeepdive/FutureDraftTab.test.tsx && npx tsc --noEmit`
Expected: PASS (2 passed) and no type errors

- [ ] **Step 6: Commit**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty"
git add web/components/ownerdeepdive/FutureDraftTab.tsx web/components/ownerdeepdive/FutureDraftTab.test.tsx web/components/OwnerDeepDive.tsx
git commit -m "feat(web): redesign Future & Draft tab — verdict-first, arsenal with past-picks table"
```

---

## Task 13: Full verification

**Files:** none (verification only)

- [ ] **Step 1: Backend + engine suites**

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty" && python -m pytest tests api/tests -q`
Expected: PASS (pre-existing unrelated failures — e.g. `test_settings_llm_cost.py` — are out of scope; note them but don't fix)

- [ ] **Step 2: Frontend unit tests + typecheck**

Run: `cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/web" && npx vitest run && npx tsc --noEmit`
Expected: PASS, no type errors

- [ ] **Step 3: Runtime smoke (local)**

Start `make dev-api` and `make dev-web`, force a refresh, then load an owner page with `?tab=future`:
- Verify Section 1 shows `#N of M` + a plain sentence.
- Verify the past-picks table renders, defaults to the most recent season, shows Current/Lowest/Highest, a +/− Avg Pick Value, Reg/Playoff Pts, and Owned/via-trade.
- Click the dashboard's Draft Ace KPI card → lands directly on the Future & Draft tab.

(Lowest/Highest will be near-equal to Current until snapshot history accumulates — expected, per the May-2026-forward constraint. Honest, self-healing over time.)

- [ ] **Step 4: Final review + finish the branch**

Use `superpowers:finishing-a-development-branch`.

---

## Self-Review

**Spec coverage:**
- §Section 1 (verdict: rank + plain sentence) → Task 12 (`verdictSentence`, rank line).
- §Section 2 (draft needs unchanged) → Task 12 (carried over verbatim).
- §Section 3 Part A (future picks) → Task 12 (chip grid retained).
- §Section 3 Part B (past-picks table, year tabs, default most recent) → Task 11.
- §Columns Current/Lowest/Highest/Avg Pick Value/Reg/Playoff + tooltips → Task 11.
- §Career-arc 3 values + May-2026 constraint → Tasks 1, 3, 11 (tooltips state the limit).
- §Acquired Owned/via-trade → Tasks 3, 5 (`acquired_set`), 11 (label).
- §Avg Pick Value +/− delta → Tasks 3 (`avg_slot_value`), 11 (`Delta`).
- §URL ?tab= nav → Task 9. §Draft Ace href → Task 10.
- §Data: `draft_picks_by_season` + `DraftPickResult` → Tasks 6, 7, 8. §Storage `drafted_picks` → Tasks 4, 5.

**Placeholder scan:** none — every code step has full content.

**Type consistency:** `DraftPickResult` field names match across engine dict keys (Task 3), Pydantic model (Task 6), grouping (Task 7), TS interface (Task 8), table (Task 11). `started_points_while_on_roster` / `build_drafted_pick_results` signatures consistent between Tasks 2/3 and their caller (Task 5). `value_extremes()` return shape `{name: (lo, hi)}` consistent between Tasks 1 and 3/5. `initialTab: TabKey` consistent between Tasks 9 page and component.

**Note on sort:** spec says "all columns sortable." This plan ships sorted-by-Avg-Pick-Value-desc (Task 7 server sort) as the default; interactive per-column sorting is deferred as a small follow-up to keep the table component focused. Flagged here so it's a conscious scope call, not an omission.
