# Franchise Rating v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Results/Skill/Outlook rating with `0.60 · Results + 0.40 · Assets`, where Results is luck-adjusted winning and Assets is what the franchise holds — and make the letter legible again on the owner hero.

**Architecture:** New pure engine signals (`all_play_win_pct`, `playoff_success`, `luck`, `young_core_share`, `roster_value_share`) feed new weight trees through the existing `compute_gm_ratings`, which is left structurally alone. The Skill pillar is dropped from scoring but its signals stay persisted, because three non-scoring consumers read them. `SCALE` is derived from a measured composite sd instead of assuming 1.0, and letter bands are stated in sd multiples that convert through it.

**Tech Stack:** Python 3.11 / pytest (engine + API), Next.js 14 / TypeScript / vitest (web), FastAPI, dataclass-based file cache.

**Spec:** `docs/superpowers/specs/2026-08-16-franchise-rating-v2-design.md`

## Global Constraints

- **Growth is out of scope.** This plan is v2 (Results + Assets). `asset_share_delta`, `get_adds`, and `engine/roster_timeline.py` are v2.1 and appear in no task here.
- **Never render "KTC" in the UI.** It is "Trade Value" / "Value".
- **All engine signal functions are pure** — no I/O, no clock reads, fully unit-testable.
- **Retired signals stay persisted.** `championships`, `made_playoffs`, `final_seed`, `points_for_rank`, `draft_skill`, `lineup_skill`, `trade_value`, `trade_production`, `youth` keep being computed and written. `compute_gm_ratings` reads only keys named in `signal_weights`, so extra keys cost nothing — and `grader.py::_playoff_rate_by_uid` plus `gm_rating_blurb.py` (twice) read them.
- **Every new API field is nullable on both sides.** `web` and `api` are separate Railway services that deploy independently on one push; either arrival order must degrade to an omitted column, never an `undefined` render.
- **Run tests with:** `pytest tests/` (engine), `cd api && pytest tests/` (API), `cd web && npx vitest --config tests/vitest.config.ts run` (web). A bare `pytest` from root breaks — `api/tests` and `tests/` are both packages named `tests`. A bare `npx vitest run` silently uses no config and fails on JSX.
- **Any UI work in `web/` → use the `furniture-styling` skill.** Any weight/signal/band change → use the `franchise-rating-calibration` skill.

---

### Task 1: All-play win percentage

The schedule-luck-free measure of a season. For each regular-season week, the share of the other rosters this roster outscored.

**Files:**
- Modify: `src/sleeper_dynasty/engine/standings.py`
- Test: `tests/test_standings.py`

**Interfaces:**
- Consumes: the same `matchups` mapping `standings_as_of` already takes — `dict[tuple[str, int, int], dict]` keyed `(league_id, week, roster_id)`, each value an entry dict carrying `team_points`.
- Produces: `all_play_win_pct(matchups, *, league_id: str, playoff_week_start: int, roster_to_user: dict[int, str]) -> dict[str, float]` — uid → win rate in `[0.0, 1.0]`.

- [ ] **Step 1: Write the failing test**

```python
def test_all_play_win_pct_scores_every_roster_against_every_other():
    # Three rosters, two regular-season weeks. Week 3 is playoffs and must be
    # excluded. A wins both weeks outright; B and C split the rest.
    matchups = {
        ("L", 1, 1): {"team_points": 100.0},
        ("L", 1, 2): {"team_points": 90.0},
        ("L", 1, 3): {"team_points": 80.0},
        ("L", 2, 1): {"team_points": 95.0},
        ("L", 2, 2): {"team_points": 60.0},
        ("L", 2, 3): {"team_points": 70.0},
        ("L", 3, 1): {"team_points": 10.0},   # playoff week, ignored
        ("L", 3, 2): {"team_points": 200.0},
        ("L", 3, 3): {"team_points": 5.0},
    }
    out = all_play_win_pct(
        matchups, league_id="L", playoff_week_start=3,
        roster_to_user={1: "ua", 2: "ub", 3: "uc"})
    assert out == {"ua": 1.0, "ub": 0.25, "uc": 0.25}


def test_all_play_win_pct_ties_count_half():
    matchups = {
        ("L", 1, 1): {"team_points": 100.0},
        ("L", 1, 2): {"team_points": 100.0},
    }
    out = all_play_win_pct(
        matchups, league_id="L", playoff_week_start=2,
        roster_to_user={1: "ua", 2: "ub"})
    assert out == {"ua": 0.5, "ub": 0.5}


def test_all_play_denominator_is_the_rosters_that_actually_played():
    # Roster 3 has no score in week 2 (bye, or a dropped pair). Week 2 must be
    # scored out of ONE opponent, not two — using league size here would
    # silently mark everyone down.
    matchups = {
        ("L", 1, 1): {"team_points": 100.0},
        ("L", 1, 2): {"team_points": 90.0},
        ("L", 1, 3): {"team_points": 80.0},
        ("L", 2, 1): {"team_points": 100.0},
        ("L", 2, 2): {"team_points": 90.0},
    }
    out = all_play_win_pct(
        matchups, league_id="L", playoff_week_start=3,
        roster_to_user={1: "ua", 2: "ub", 3: "uc"})
    # ua: 2/2 + 1/1 = 3/3;  ub: 1/2 + 0/1 = 1/3;  uc: 0/2 = 0/2
    assert out["ua"] == 1.0
    assert out["ub"] == pytest.approx(1 / 3)
    assert out["uc"] == 0.0


def test_all_play_win_pct_skips_rosters_with_no_played_weeks():
    out = all_play_win_pct(
        {}, league_id="L", playoff_week_start=15, roster_to_user={1: "ua"})
    assert out == {}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_standings.py -k all_play -v`
Expected: FAIL with `NameError: name 'all_play_win_pct' is not defined`

- [ ] **Step 3: Write the implementation**

Append to `src/sleeper_dynasty/engine/standings.py`:

```python
def all_play_win_pct(
    matchups: dict[tuple[str, int, int], dict],
    *,
    league_id: str,
    playoff_week_start: int,
    roster_to_user: dict[int, str],
) -> dict[str, float]:
    """Share of all-play matchups won, over one league's regular season.

    For each week, every roster is scored against every *other* roster that
    played that week: a higher score is a win, an equal score is half. This is
    the schedule-luck-free reading of a season — it uses the same weekly
    ``team_points`` as ``standings_as_of`` and answers "how good were you"
    rather than "who did you happen to draw".

    The denominator is the rosters that actually played that week, NOT the
    league size. A bye, or a matchup pair dropped upstream for having no score,
    removes those rosters from that week entirely; dividing by league size
    would mark every remaining roster down for an absence.

    Rosters with no played weeks are omitted rather than returned at 0.0 — no
    games is an absence, not a shutout.
    """
    by_week: dict[int, dict[int, float]] = {}
    for (lg, week, roster_id), entry in matchups.items():
        if lg != league_id or week >= playoff_week_start or week < 1:
            continue
        pts = entry.get("team_points")
        if pts is None:
            continue
        by_week.setdefault(week, {})[roster_id] = float(pts)

    wins: dict[int, float] = {}
    played: dict[int, int] = {}
    for scores in by_week.values():
        roster_ids = list(scores)
        if len(roster_ids) < 2:
            continue
        for rid in roster_ids:
            mine = scores[rid]
            beat = sum(1 for other in roster_ids if other != rid and mine > scores[other])
            tied = sum(1 for other in roster_ids if other != rid and mine == scores[other])
            wins[rid] = wins.get(rid, 0.0) + beat + 0.5 * tied
            played[rid] = played.get(rid, 0) + len(roster_ids) - 1

    out: dict[str, float] = {}
    for rid, n in played.items():
        uid = roster_to_user.get(rid)
        if uid and n:
            out[uid] = wins[rid] / n
    return out
```

Add `import pytest` at the top of the test file if it is not already there.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_standings.py -k all_play -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/standings.py tests/test_standings.py
git commit -m "feat(engine): all-play win percentage, the luck-free reading of a season"
```

---

### Task 2: Recency decay and the Results signal trio

Season weighting plus the three signals that replace the old five.

**Files:**
- Create: `src/sleeper_dynasty/engine/results_signals.py`
- Test: `tests/test_results_signals.py`

**Interfaces:**
- Consumes: `all_play_win_pct` from Task 1 (the caller supplies its per-season output).
- Produces:
  - `season_weight(season: int, latest_played_season: int, half_life: float = 2.0) -> float`
  - `decayed_mean(by_season: dict[int, float], latest_played_season: int) -> float`
  - `results_signals(*, all_play_by_season: dict[int, dict[str, float]], season_records: dict[int, dict[str, dict]], owners: list[str], latest_played_season: int) -> dict[str, dict[str, float]]` — uid → `{"expected_wins", "playoff_success", "luck"}`
  - `latest_played_season(season_records: dict[int, dict[str, dict]], min_weeks: int = 4) -> int | None`

- [ ] **Step 1: Write the failing tests**

```python
import pytest

from sleeper_dynasty.engine.results_signals import (
    decayed_mean, latest_played_season, results_signals, season_weight,
)


def test_season_weight_halves_every_two_seasons():
    assert season_weight(2025, 2025) == 1.0
    assert season_weight(2024, 2025) == pytest.approx(0.7071, abs=1e-4)
    assert season_weight(2023, 2025) == pytest.approx(0.5)


def test_season_weight_is_clamped_at_one_for_future_seasons():
    # draft_skill_by_season already holds a 2026 class while 2025 is the
    # anchor. Unclamped this returns 1.414 and the least-played evidence
    # outweighs the anchor.
    assert season_weight(2026, 2025) == 1.0


def test_decayed_mean_weights_recent_seasons_more():
    out = decayed_mean({2023: 0.0, 2024: 0.0, 2025: 1.0}, 2025)
    # 1.0 / (1.0 + 0.7071 + 0.5)
    assert out == pytest.approx(1.0 / 2.2071, abs=1e-4)


def test_decayed_mean_of_nothing_is_zero():
    assert decayed_mean({}, 2025) == 0.0


def test_latest_played_season_ignores_a_season_under_the_week_floor():
    records = {
        2025: {"u": {"wins": 7, "losses": 7, "ties": 0}},
        2026: {"u": {"wins": 1, "losses": 1, "ties": 0}},   # 2 games, below floor
    }
    assert latest_played_season(records, min_weeks=4) == 2025


def test_latest_played_season_is_none_when_nothing_has_been_played():
    assert latest_played_season({2026: {"u": {"wins": 0, "losses": 0, "ties": 0}}}) is None


def test_results_signals_computes_the_trio():
    all_play = {2025: {"ua": 0.75, "ub": 0.25}}
    records = {
        2025: {
            "ua": {"wins": 7, "losses": 7, "ties": 0, "made_playoffs": True,
                   "rounds_won": 2, "champion": True},
            "ub": {"wins": 7, "losses": 7, "ties": 0, "made_playoffs": False,
                   "rounds_won": 0, "champion": False},
        }
    }
    out = results_signals(
        all_play_by_season=all_play, season_records=records,
        owners=["ua", "ub"], latest_played_season=2025)

    assert out["ua"]["expected_wins"] == pytest.approx(0.75)
    # 0.5 berth + 1.0 * 2 rounds + 1.5 championship
    assert out["ua"]["playoff_success"] == pytest.approx(4.0)
    # actual .500 minus expected .750
    assert out["ua"]["luck"] == pytest.approx(-0.25)

    assert out["ub"]["playoff_success"] == pytest.approx(0.0)
    assert out["ub"]["luck"] == pytest.approx(0.25)


def test_luck_is_orthogonal_to_expected_wins_by_construction():
    # An owner who scores well and loses close games has NEGATIVE luck; the
    # signal isolates schedule noise instead of re-injecting it.
    all_play = {2025: {"ua": 0.90}}
    records = {2025: {"ua": {"wins": 7, "losses": 7, "ties": 0,
                             "made_playoffs": False, "rounds_won": 0,
                             "champion": False}}}
    out = results_signals(all_play_by_season=all_play, season_records=records,
                          owners=["ua"], latest_played_season=2025)
    assert out["ua"]["luck"] < 0


def test_results_signals_gives_every_requested_owner_a_row():
    out = results_signals(
        all_play_by_season={}, season_records={}, owners=["ua"],
        latest_played_season=2025)
    assert out == {"ua": {"expected_wins": 0.0, "playoff_success": 0.0, "luck": 0.0}}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_results_signals.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sleeper_dynasty.engine.results_signals'`

- [ ] **Step 3: Write the implementation**

Create `src/sleeper_dynasty/engine/results_signals.py`:

```python
"""The Results pillar: luck-adjusted winning, recency-weighted.

Three signals replace the five that v1 used. Four of those five
(``championships``, ``playoff_depth``, ``made_playoffs``, ``final_seed``)
encoded one binary — did you make the playoffs — and correlated pairwise at
r +0.61 to +0.91, so an owner who never made the field was charged for it four
times. Here the berth is worth half a round win inside one signal, and
``points_for_rank`` is subsumed by ``expected_wins``, which measures the same
scoring quality at weekly rather than seasonal resolution.

Pure: no I/O, no clock.
"""

from __future__ import annotations

HALF_LIFE_SEASONS = 2.0

# A season needs this many completed games before it can anchor the decay.
# Without it the whole chain re-anchors in week 2 of a new season and every
# owner's grade jumps for reasons unrelated to their play.
MIN_ANCHOR_WEEKS = 4

BERTH_CREDIT = 0.5
ROUND_CREDIT = 1.0
TITLE_CREDIT = 1.5


def season_weight(
    season: int, latest_played_season: int, half_life: float = HALF_LIFE_SEASONS
) -> float:
    """Recency weight for one season, halving every ``half_life`` seasons.

    Clamped at 1.0. A season *ahead* of the anchor — a rookie class already
    drafted for a season nobody has played — must never outweigh the anchor.
    """
    return min(1.0, 0.5 ** ((latest_played_season - season) / half_life))


def decayed_mean(by_season: dict[int, float], latest_played_season: int) -> float:
    """Recency-weighted mean of a per-season quantity. Empty -> 0.0."""
    num = 0.0
    den = 0.0
    for season, value in by_season.items():
        w = season_weight(int(season), latest_played_season)
        num += w * float(value)
        den += w
    return (num / den) if den else 0.0


def _games(rec: dict) -> int:
    return int(rec.get("wins", 0)) + int(rec.get("losses", 0)) + int(rec.get("ties", 0))


def latest_played_season(
    season_records: dict[int, dict[str, dict]], min_weeks: int = MIN_ANCHOR_WEEKS
) -> int | None:
    """The most recent season with real games behind it, or None.

    None means the league has played nothing yet; callers must render an
    absence rather than grade it.
    """
    played = [
        int(season)
        for season, rows in season_records.items()
        if any(_games(rec) >= min_weeks for rec in rows.values())
    ]
    return max(played) if played else None


def _win_pct(rec: dict) -> float:
    n = _games(rec)
    if not n:
        return 0.0
    return (int(rec.get("wins", 0)) + 0.5 * int(rec.get("ties", 0))) / n


def _playoff_points(rec: dict) -> float:
    return (
        (BERTH_CREDIT if rec.get("made_playoffs") else 0.0)
        + ROUND_CREDIT * float(rec.get("rounds_won", 0) or 0)
        + (TITLE_CREDIT if rec.get("champion") else 0.0)
    )


def results_signals(
    *,
    all_play_by_season: dict[int, dict[str, float]],
    season_records: dict[int, dict[str, dict]],
    owners: list[str],
    latest_played_season: int,
) -> dict[str, dict[str, float]]:
    """uid -> {expected_wins, playoff_success, luck}, each recency-weighted.

    ``luck`` is ``actual_wins - expected_wins`` and is therefore orthogonal to
    ``expected_wins`` by construction. It replaces raw ``actual_wins``, which
    was expected wins plus schedule noise and re-injected the very thing the
    pillar exists to remove.
    """
    out: dict[str, dict[str, float]] = {}
    for uid in owners:
        expected: dict[int, float] = {}
        actual: dict[int, float] = {}
        playoff: dict[int, float] = {}
        for season, rows in season_records.items():
            rec = rows.get(uid)
            if rec is None or _games(rec) == 0:
                continue
            s = int(season)
            actual[s] = _win_pct(rec)
            playoff[s] = _playoff_points(rec)
            ap = (all_play_by_season.get(s) or {}).get(uid)
            if ap is not None:
                expected[s] = float(ap)

        exp = decayed_mean(expected, latest_played_season)
        act = decayed_mean(actual, latest_played_season)
        out[uid] = {
            "expected_wins": exp,
            "playoff_success": decayed_mean(playoff, latest_played_season),
            "luck": act - exp,
        }
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_results_signals.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/results_signals.py tests/test_results_signals.py
git commit -m "feat(engine): Results signals — expected wins, playoff success, isolated luck"
```

---

### Task 3: Asset signals — young-core share and roster value share

**Files:**
- Create: `src/sleeper_dynasty/engine/asset_signals.py`
- Test: `tests/test_asset_signals.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `asset_signals(*, current_holders: dict[str, str], value_by_player: dict[str, float], age_by_player: dict[str, int], owners: list[str], young_max_age: int = 25) -> dict[str, dict[str, float]]` — uid → `{"roster_value_share", "young_core_share"}`.

- [ ] **Step 1: Write the failing tests**

```python
import pytest

from sleeper_dynasty.engine.asset_signals import asset_signals


def test_shares_are_league_relative_and_sum_to_one():
    out = asset_signals(
        current_holders={"p1": "ua", "p2": "ub"},
        value_by_player={"p1": 75.0, "p2": 25.0},
        age_by_player={"p1": 24, "p2": 30},
        owners=["ua", "ub"])
    assert out["ua"]["roster_value_share"] == pytest.approx(0.75)
    assert out["ub"]["roster_value_share"] == pytest.approx(0.25)
    total = sum(o["roster_value_share"] for o in out.values())
    assert total == pytest.approx(1.0)


def test_young_core_share_is_value_weighted_not_a_head_count():
    # One 24-year-old worth 90 and eight veterans worth 10 between them. A mean
    # age would call this an old roster; the value that matters is young.
    holders = {"star": "ua", **{f"vet{i}": "ua" for i in range(8)}}
    values = {"star": 90.0, **{f"vet{i}": 1.25 for i in range(8)}}
    ages = {"star": 24, **{f"vet{i}": 31 for i in range(8)}}
    out = asset_signals(current_holders=holders, value_by_player=values,
                        age_by_player=ages, owners=["ua"])
    assert out["ua"]["young_core_share"] == pytest.approx(0.9)


def test_unknown_age_players_are_excluded_from_both_sides():
    # A player with no birth_date must not sit in the denominator alone —
    # that systematically penalises deep-bench rookies, exactly the owners
    # the signal exists to reward.
    out = asset_signals(
        current_holders={"young": "ua", "mystery": "ua"},
        value_by_player={"young": 50.0, "mystery": 50.0},
        age_by_player={"young": 23},          # no age for "mystery"
        owners=["ua"])
    assert out["ua"]["young_core_share"] == pytest.approx(1.0)
    # ...but an unpriced-age player still counts as owned value.
    assert out["ua"]["roster_value_share"] == pytest.approx(1.0)


def test_empty_roster_is_zero_not_a_division_error():
    out = asset_signals(current_holders={}, value_by_player={},
                        age_by_player={}, owners=["ua"])
    assert out["ua"] == {"roster_value_share": 0.0, "young_core_share": 0.0}


def test_every_requested_owner_gets_a_row():
    out = asset_signals(
        current_holders={"p1": "ua"}, value_by_player={"p1": 10.0},
        age_by_player={"p1": 22}, owners=["ua", "ub"])
    assert set(out) == {"ua", "ub"}
    assert out["ub"]["roster_value_share"] == 0.0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_asset_signals.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

Create `src/sleeper_dynasty/engine/asset_signals.py`:

```python
"""The Assets pillar: what a franchise holds right now.

Both signals are *shares* rather than raw totals, so they are scale-free and
comparable without depending on how a particular valuation source is scaled.

``young_core_share`` replaces the old negated mean age. A straight mean over a
roster measures roster filler: it ranked one owner 10th of 12 on youth while
his most valuable assets were a 24-year-old QB and two young receivers, because
eight veterans dragged the average the young core should have dominated.

Pure: no I/O, no clock.
"""

from __future__ import annotations

YOUNG_MAX_AGE = 25


def asset_signals(
    *,
    current_holders: dict[str, str],
    value_by_player: dict[str, float],
    age_by_player: dict[str, int],
    owners: list[str],
    young_max_age: int = YOUNG_MAX_AGE,
) -> dict[str, dict[str, float]]:
    """uid -> {roster_value_share, young_core_share}.

    - ``roster_value_share``: this owner's roster value over the league's total.
    - ``young_core_share``: the share of *this owner's* value held by players
      aged ``young_max_age`` or younger.

    Players with an unknown age are excluded from **both** sides of the
    young-core ratio. Leaving them in the denominator only would bias the
    signal down for whoever rosters the most unlisted deep-bench rookies. They
    still count toward roster value, which does not depend on age.
    """
    value: dict[str, float] = {u: 0.0 for u in owners}
    aged_value: dict[str, float] = {u: 0.0 for u in owners}
    young_value: dict[str, float] = {u: 0.0 for u in owners}

    for pid, uid in current_holders.items():
        v = float(value_by_player.get(pid, 0.0) or 0.0)
        value.setdefault(uid, 0.0)
        aged_value.setdefault(uid, 0.0)
        young_value.setdefault(uid, 0.0)
        value[uid] += v
        age = age_by_player.get(pid)
        if age is None:
            continue
        aged_value[uid] += v
        if int(age) <= young_max_age:
            young_value[uid] += v

    league_total = sum(value.values())
    out: dict[str, dict[str, float]] = {}
    for uid in value:
        denom = aged_value[uid]
        out[uid] = {
            "roster_value_share": (value[uid] / league_total) if league_total else 0.0,
            "young_core_share": (young_value[uid] / denom) if denom else 0.0,
        }
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_asset_signals.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/asset_signals.py tests/test_asset_signals.py
git commit -m "feat(engine): Assets signals — value share and a value-weighted young core"
```

---

### Task 4: Weight trees, calibrated SCALE, and letter bands

**Files:**
- Modify: `src/sleeper_dynasty/engine/gm_rating.py`
- Test: `tests/test_gm_rating.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `V2_PILLAR_WEIGHTS: dict[str, dict[str, float]]` with keys `"v2_dynasty"`, `"v2_keeper"`, `"v2_redraft"`
  - `V2_SIGNAL_WEIGHTS`, `V2_KEEPER_SIGNAL_WEIGHTS`, `V2_REDRAFT_SIGNAL_WEIGHTS`
  - `POINTS_PER_SD: int`, `REFERENCE_COMPOSITE_SD: float`, `SCALE: float`
  - `rating_to_letter(rating: int) -> str` — unchanged signature, new bands

- [ ] **Step 1: Write the failing tests**

```python
def test_v2_trees_are_normalized():
    for name, tree in V2_PILLAR_WEIGHTS.items():
        assert sum(tree.values()) == pytest.approx(1.0), name
    for name, tree in (
        ("dynasty", V2_SIGNAL_WEIGHTS),
        ("keeper", V2_KEEPER_SIGNAL_WEIGHTS),
        ("redraft", V2_REDRAFT_SIGNAL_WEIGHTS),
    ):
        for pillar, sigs in tree.items():
            assert sum(sigs.values()) == pytest.approx(1.0), f"{name}/{pillar}"


def test_every_v2_pillar_tree_has_a_matching_signal_tree():
    # compute_gm_ratings indexes signal_weights by pillar name; a mismatch is
    # a KeyError at runtime rather than a bad number.
    pairs = [
        ("v2_dynasty", V2_SIGNAL_WEIGHTS),
        ("v2_keeper", V2_KEEPER_SIGNAL_WEIGHTS),
        ("v2_redraft", V2_REDRAFT_SIGNAL_WEIGHTS),
    ]
    for model, sigs in pairs:
        assert set(V2_PILLAR_WEIGHTS[model]) == set(sigs), model


def test_redraft_scores_results_only():
    assert V2_PILLAR_WEIGHTS["v2_redraft"] == {"results": 1.0}


def test_keeper_assets_drops_young_core_and_renormalizes():
    assets = V2_KEEPER_SIGNAL_WEIGHTS["assets"]
    assert "young_core_share" not in assets
    assert sum(assets.values()) == pytest.approx(1.0)


def test_letter_bands_are_monotone_and_have_no_f():
    deltas = [d for d, _ in LETTER_BANDS]
    assert deltas == sorted(deltas, reverse=True)
    assert "F" not in [letter for _, letter in LETTER_BANDS]
    assert rating_to_letter(BASE - 100_000) == "D-"


def test_c_plus_exists_and_c_straddles_the_base():
    letters = [letter for _, letter in LETTER_BANDS]
    assert "C+" in letters
    assert rating_to_letter(BASE) == "C"


def test_scale_is_derived_from_the_measured_composite_sd():
    # Bands are stated in sd multiples and must convert through SCALE. Assuming
    # composite sd == 1.0 is what made v1's band table disagree with its own
    # sd column.
    assert SCALE == pytest.approx(POINTS_PER_SD / REFERENCE_COMPOSITE_SD)
    # One reference sd of composite is worth exactly POINTS_PER_SD points.
    assert round(SCALE * REFERENCE_COMPOSITE_SD) == POINTS_PER_SD
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_gm_rating.py -k "v2 or letter_bands or c_plus or scale" -v`
Expected: FAIL with `NameError: name 'V2_PILLAR_WEIGHTS' is not defined`

- [ ] **Step 3: Write the implementation**

In `src/sleeper_dynasty/engine/gm_rating.py`, add below the existing trees:

```python
# --- v2: winning + building. Skill is dropped from scoring (nothing in it
# persisted year to year: draft r~+0.10, lineup r~+0.04, and both trade signals
# were NEGATIVELY self-correlated) and is measured through its consequences
# instead. Growth (asset-share trajectory) arrives in v2.1 and takes its weight
# out of Assets.
V2_PILLAR_WEIGHTS = {
    "v2_dynasty": {"results": 0.60, "assets": 0.40},
    # Same split as dynasty; keeper differs only inside Assets.
    "v2_keeper": {"results": 0.60, "assets": 0.40},
    # Nothing carries over, so Assets has no subject. Dropped, not zeroed.
    "v2_redraft": {"results": 1.00},
}

_V2_RESULTS = {"expected_wins": 0.55, "playoff_success": 0.30, "luck": 0.15}

V2_SIGNAL_WEIGHTS = {
    "results": dict(_V2_RESULTS),
    "assets": {
        "roster_value_share": 0.45, "young_core_share": 0.35, "draft_capital": 0.20,
    },
}

# Two or three keepers is not a young roster, so young-core share is noise.
# Dropped and the survivors renormalized over 0.65.
V2_KEEPER_SIGNAL_WEIGHTS = {
    "results": dict(_V2_RESULTS),
    "assets": {"roster_value_share": 0.70, "draft_capital": 0.30},
}

V2_REDRAFT_SIGNAL_WEIGHTS = {"results": dict(_V2_RESULTS)}
```

Replace the `SCALE` constant and `LETTER_BANDS` block:

```python
# One reference standard deviation of composite is worth this many rating
# points. Bands below are stated in sd multiples and convert through it.
POINTS_PER_SD = 275

# Measured composite sd of the v2 dynasty tree on the reference league. v1
# assumed 1.0 while the real value was 0.70, which is why its `C` band spanned
# +/-0.10 sd and ~30% of any league graded D+ or worse by construction.
# Re-measure with the `franchise-rating-calibration` skill after any tree
# change and update this number in the same commit.
REFERENCE_COMPOSITE_SD = 0.906

SCALE = POINTS_PER_SD / REFERENCE_COMPOSITE_SD

# (sd multiple, letter), high to low. No F: a twelve-owner league spans roughly
# +/-1.75 sd, so an F could only ever fire by construction or never. The scale
# runs A+ to D- and says so.
_BAND_SD: list[tuple[float, str]] = [
    (1.40, "A+"), (1.15, "A"), (0.90, "A-"),
    (0.68, "B+"), (0.45, "B"), (0.22, "B-"),
    (0.07, "C+"), (-0.22, "C"), (-0.45, "C-"),
    (-0.68, "D+"), (-0.95, "D"),
]

LETTER_BANDS: list[tuple[int, str]] = [
    (round(mult * POINTS_PER_SD), letter) for mult, letter in _BAND_SD
]
```

Update `rating_to_letter`'s fallback from `"F"` to `"D-"`, and its docstring to say the scale is league-relative and runs A+ to D−.

- [ ] **Step 4: Run the full engine rating suite**

Run: `pytest tests/test_gm_rating.py tests/test_gm_rating_redraft.py -v`
Expected: all pass. If an existing test asserts an `"F"` letter or a specific old band delta, update it to the new ladder — those assertions encode v1's calibration, not a behaviour worth keeping.

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/gm_rating.py tests/test_gm_rating.py tests/test_gm_rating_redraft.py
git commit -m "feat(engine): v2 trees, SCALE derived from measured composite sd, no F band"
```

---

### Task 5: Wire the new signals into the refresh

**Files:**
- Modify: `api/app/services/rating_signals.py`
- Test: `api/tests/services/test_rating_signals_v2.py` (create)

**Interfaces:**
- Consumes: `all_play_win_pct` (Task 1), `results_signals` / `latest_played_season` (Task 2), `asset_signals` (Task 3).
- Produces: `compute_rating_signals` returns the same 4-tuple, with `outcome_signals` gaining `expected_wins` / `playoff_success` / `luck` and `outlook_signals` gaining `roster_value_share` / `young_core_share`. **No existing key is removed.**

- [ ] **Step 1: Write the failing test**

```python
"""v2 signals reach the refresh output without disturbing the v1 keys."""

from app.services.rating_signals import compute_rating_signals


def _supporting():
    return {
        "matchups": {
            ("L1", 1, 1): {"team_points": 100.0},
            ("L1", 1, 2): {"team_points": 80.0},
            ("L1", 2, 1): {"team_points": 90.0},
            ("L1", 2, 2): {"team_points": 95.0},
        },
        "roster_to_user_by_league": {"L1": {1: "ua", 2: "ub"}},
        "league_season_by_id": {"L1": 2025},
        "playoff_week_start_by_league": {"L1": 3},
        "winners_bracket_by_league": {"L1": []},
        "losers_bracket_by_league": {"L1": []},
        "num_playoff_teams_by_league": {"L1": 1},
        "ktc_by_player_id": {},
        "player_ages": {"p1": 24, "p2": 31},
        "owners": {"ua": {}, "ub": {}},
    }


def test_v2_results_keys_are_emitted():
    osig, olsig, _lineup, _seasons = compute_rating_signals(
        _supporting(), current_holders={"p1": "ua", "p2": "ub"})
    for uid in ("ua", "ub"):
        assert {"expected_wins", "playoff_success", "luck"} <= set(osig[uid])


def test_v1_outcome_keys_survive_for_their_non_scoring_consumers():
    # grader._playoff_rate_by_uid and gm_rating_blurb both read these. Dropping
    # them would silently tell a champion's blurb writer he has no titles.
    osig, _olsig, _lineup, _seasons = compute_rating_signals(
        _supporting(), current_holders={})
    assert {"championships", "made_playoffs", "final_seed", "points_for_rank"} <= set(osig["ua"])


def test_v2_asset_keys_are_emitted_alongside_the_old_ones():
    _osig, olsig, _lineup, _seasons = compute_rating_signals(
        _supporting(), current_holders={"p1": "ua", "p2": "ub"})
    assert {"roster_value_share", "young_core_share"} <= set(olsig["ua"])
    assert {"roster_value", "draft_capital", "youth"} <= set(olsig["ua"])


def test_expected_wins_is_all_play_not_head_to_head():
    # ua outscored ub in week 1 and lost week 2: all-play .500 over two weeks.
    osig, _olsig, _lineup, _seasons = compute_rating_signals(
        _supporting(), current_holders={})
    assert osig["ua"]["expected_wins"] == 0.5
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd api && pytest tests/services/test_rating_signals_v2.py -v`
Expected: FAIL — `KeyError: 'expected_wins'`

- [ ] **Step 3: Write the implementation**

In `api/app/services/rating_signals.py`, add imports:

```python
from sleeper_dynasty.engine.asset_signals import asset_signals
from sleeper_dynasty.engine.results_signals import (
    latest_played_season as _latest_played_season, results_signals,
)
from sleeper_dynasty.engine.standings import all_play_win_pct, standings_as_of
```

Inside the per-league loop that already builds `standings_by_season`, add an all-play accumulator:

```python
    all_play_by_season: dict[int, dict[str, float]] = {}
```

and inside the loop, beside the `standings_as_of` call:

```python
        all_play_by_season[int(season)] = all_play_win_pct(
            matchups, league_id=lg, playoff_week_start=pws, roster_to_user=r2u)
```

After the existing `osig = outcome_signals(...)` call, merge the v2 Results keys in. `season_records` is already built later in this function — move its construction above this point if necessary, or pass the same `standings_by_season` / `brackets_by_season` you already have:

```python
    # v2 Results. Merged into the same dict rather than replacing it: v1's keys
    # have three non-scoring consumers (grader._playoff_rate_by_uid, and
    # gm_rating_blurb twice), and compute_gm_ratings only reads the keys named
    # in its signal_weights, so carrying both costs nothing.
    records_by_season = {
        season: {
            row.owner_id: {
                "wins": row.wins, "losses": row.losses, "ties": row.ties,
                "made_playoffs": bool(
                    npt_by_season.get(season) and row.rank <= npt_by_season[season]),
                "rounds_won": int(
                    (brackets_by_season.get(season, {}).get(row.owner_id) or {})
                    .get("rounds_won", 0) or 0),
                "champion": bool(
                    (brackets_by_season.get(season, {}).get(row.owner_id) or {})
                    .get("champion")),
            }
            for row in rows
        }
        for season, rows in standings_by_season.items()
    }
    anchor = _latest_played_season(records_by_season)
    if anchor is not None:
        rsig = results_signals(
            all_play_by_season=all_play_by_season,
            season_records=records_by_season,
            owners=owners, latest_played_season=anchor)
        for uid, sigs in rsig.items():
            osig.setdefault(uid, {}).update(sigs)
```

Where `olsig` is assembled, merge the asset shares in:

```python
    ktc_floats_by_pid = {pid: _ktc_value(v) for pid, v in ktc.items()}
    assets = asset_signals(
        current_holders=current_holders, value_by_player=ktc_floats_by_pid,
        age_by_player=ages, owners=owners)
    for uid, sigs in assets.items():
        olsig.setdefault(uid, {}).update(sigs)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd api && pytest tests/services/test_rating_signals_v2.py -v && pytest tests/ -q`
Expected: new tests pass, existing API suite still green.

- [ ] **Step 5: Commit**

```bash
git add api/app/services/rating_signals.py api/tests/services/test_rating_signals_v2.py
git commit -m "feat(api): emit v2 Results and Assets signals alongside the v1 keys"
```

---

### Task 6: Select the v2 tree

**Files:**
- Modify: `api/app/services/franchise_redesign.py`
- Test: `api/tests/services/test_franchise_redesign_v2.py` (create)

**Interfaces:**
- Consumes: `V2_PILLAR_WEIGHTS`, `V2_SIGNAL_WEIGHTS`, `V2_KEEPER_SIGNAL_WEIGHTS`, `V2_REDRAFT_SIGNAL_WEIGHTS` (Task 4); the merged signal dicts (Task 5).
- Produces: `live_ratings(entry, year="all")` returns rows whose `pillars` are keyed `results` / `assets` (or `results` alone for redraft) and whose `model` is `v2_dynasty` / `v2_keeper` / `v2_redraft`.

- [ ] **Step 1: Write the failing test**

```python
from app.services.franchise_redesign import build_v2_pillars, live_ratings, model_for


def test_dynasty_selects_the_v2_dynasty_tree(dynasty_entry):
    assert model_for(dynasty_entry) == "v2_dynasty"
    rows = live_ratings(dynasty_entry)
    row = next(iter(rows.values()))
    assert row["model"] == "v2_dynasty"
    assert set(row["pillars"]) == {"results", "assets"}


def test_redraft_gets_results_only(redraft_entry):
    rows = live_ratings(redraft_entry)
    row = next(iter(rows.values()))
    assert set(row["pillars"]) == {"results"}


def test_pillars_read_the_persisted_signal_dicts(dynasty_entry):
    pillars = build_v2_pillars(dynasty_entry)
    uid = next(iter(dynasty_entry.owners))
    assert "expected_wins" in pillars[uid]["results"]
    assert "young_core_share" in pillars[uid]["assets"]


def test_no_skill_pillar_survives(dynasty_entry):
    rows = live_ratings(dynasty_entry)
    for row in rows.values():
        assert "skill" not in row["pillars"]
```

Reuse the existing fixture style in `api/tests/services/_grader_fixtures.py`; add `dynasty_entry` and `redraft_entry` fixtures there that build a `ChainCacheEntry` with `outcome_signals` / `outlook_signals` populated for two owners and `capabilities` set to `{"format": "dynasty"}` and `{"format": "redraft"}` respectively.

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd api && pytest tests/services/test_franchise_redesign_v2.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_v2_pillars'`

- [ ] **Step 3: Write the implementation**

Replace `build_redesign_pillars` / the model maps in `api/app/services/franchise_redesign.py`:

```python
from sleeper_dynasty.engine.gm_rating import (
    V2_KEEPER_SIGNAL_WEIGHTS, V2_PILLAR_WEIGHTS, V2_REDRAFT_SIGNAL_WEIGHTS,
    V2_SIGNAL_WEIGHTS, compute_gm_ratings,
)

LIVE_MODEL = "v2_dynasty"
_MODEL_BY_FORMAT = {"keeper": "v2_keeper", "redraft": "v2_redraft"}
_SIGNALS_BY_MODEL = {
    "v2_dynasty": V2_SIGNAL_WEIGHTS,
    "v2_keeper": V2_KEEPER_SIGNAL_WEIGHTS,
    "v2_redraft": V2_REDRAFT_SIGNAL_WEIGHTS,
}


def build_v2_pillars(entry: ChainCacheEntry) -> dict[str, dict[str, dict[str, float]]]:
    """uid -> {"results", "assets"} signal sub-dicts for compute_gm_ratings.

    Both sub-dicts are read straight off the persisted signal dicts. v2 needs
    no per-trade derivation at all — the Skill pillar it replaced was the only
    thing that did, which is why `trade_skill_signals` and the year filter are
    gone from this module.
    """
    owners = list(entry.owners)
    outcomes = entry.outcome_signals or {}
    outlook = entry.outlook_signals or {}
    out: dict[str, dict[str, dict[str, float]]] = {}
    for uid in owners:
        oc = outcomes.get(uid, {})
        ol = outlook.get(uid, {})
        out[uid] = {
            "results": {
                "expected_wins": float(oc.get("expected_wins") or 0.0),
                "playoff_success": float(oc.get("playoff_success") or 0.0),
                "luck": float(oc.get("luck") or 0.0),
            },
            "assets": {
                "roster_value_share": float(ol.get("roster_value_share") or 0.0),
                "young_core_share": float(ol.get("young_core_share") or 0.0),
                "draft_capital": float(ol.get("draft_capital") or 0.0),
            },
        }
    return out


def live_ratings(entry: ChainCacheEntry, *, year: Year = "all") -> dict[str, dict]:
    """The live Franchise Rating under this league's v2 tree."""
    model = model_for(entry)
    out = compute_gm_ratings(
        build_v2_pillars(entry),
        pillar_weights=V2_PILLAR_WEIGHTS[model],
        signal_weights=_SIGNALS_BY_MODEL[model],
    )
    for row in out.values():
        row["model"] = model
    return out
```

Keep `model_for` as it is, but point its default at the new `LIVE_MODEL`. Delete `_trade_records` and the `trade_skill_signals` import — nothing calls them now. The `year` parameter is retained for call-site compatibility and is unused; document that in the docstring.

- [ ] **Step 4: Run the tests**

Run: `cd api && pytest tests/services/test_franchise_redesign_v2.py -v && pytest tests/ -q`
Expected: new tests pass. Existing tests referencing `results_led` or a `skill` pillar will fail — update them to the v2 tree; those assertions encode the model being replaced.

- [ ] **Step 5: Commit**

```bash
git add api/app/services/franchise_redesign.py api/tests/services/
git commit -m "feat(api): score the v2 tree — Results and Assets, no Skill pillar"
```

---

### Task 7: The guard tests that keep the model honest

**Files:**
- Create: `tests/test_gm_rating_guards.py`
- Test: itself

**Interfaces:**
- Consumes: everything from Tasks 1–6.
- Produces: no production code. This task is the safety net the spec's validation section calls for.

- [ ] **Step 1: Write the tests**

```python
"""Invariants that a weight change must not break.

These exist because v1 shipped three separate fixes that were each cancelled
by the layer beneath them. A guard that cannot fail is worse than no guard, so
each of these is written to actually go red on the mistake it names.
"""

import statistics

import pytest

from sleeper_dynasty.engine.gm_rating import (
    BASE, V2_PILLAR_WEIGHTS, V2_SIGNAL_WEIGHTS, compute_gm_ratings,
)


def _league(n: int = 12) -> dict:
    """n owners with spread-out, deterministic signal values."""
    return {
        f"u{i}": {
            "results": {
                "expected_wins": 0.30 + 0.04 * i,
                "playoff_success": float(i % 5),
                "luck": 0.05 - 0.01 * (i % 7),
            },
            "assets": {
                "roster_value_share": 0.05 + 0.005 * i,
                "young_core_share": 0.20 + 0.03 * (i % 6),
                "draft_capital": 20_000.0 + 900.0 * (i % 8),
            },
        }
        for i in range(n)
    }


def _rate():
    return compute_gm_ratings(
        _league(), pillar_weights=V2_PILLAR_WEIGHTS["v2_dynasty"],
        signal_weights=V2_SIGNAL_WEIGHTS)


def test_signal_contributions_sum_to_their_pillar():
    # OverviewTab reconciles 1500 + sum(contributions) against the rating on
    # screen and shows a visible "gap" note when they disagree.
    for row in _rate().values():
        for pillar in row["pillars"].values():
            total = sum(s["contribution"] for s in pillar["signals"].values())
            assert abs(total - pillar["contribution"]) <= 1


def test_base_plus_pillar_contributions_equals_the_rating():
    for row in _rate().values():
        total = BASE + sum(p["contribution"] for p in row["pillars"].values())
        assert abs(total - row["rating"]) <= 2


def test_realized_pillar_variance_share_matches_the_stated_weight():
    rows = _rate()
    uids = list(rows)
    composite = [rows[u]["rating"] - BASE for u in uids]
    var = statistics.pvariance(composite)
    for pillar, weight in V2_PILLAR_WEIGHTS["v2_dynasty"].items():
        contrib = [rows[u]["pillars"][pillar]["contribution"] for u in uids]
        mc = statistics.mean(contrib)
        mk = statistics.mean(composite)
        cov = sum((a - mc) * (b - mk) for a, b in zip(contrib, composite)) / len(uids)
        share = cov / var
        # Convention: share = cov(pillar_contribution, composite) / var(composite).
        # Loose bound - the point is to catch a pillar that has silently become
        # twice or half its stated influence, not to pin a decimal.
        assert weight - 0.20 <= share <= weight + 0.20, (pillar, share)


def test_a_league_of_identical_owners_does_not_spread():
    flat = {f"u{i}": _league(1)["u0"] for i in range(12)}
    rows = compute_gm_ratings(
        flat, pillar_weights=V2_PILLAR_WEIGHTS["v2_dynasty"],
        signal_weights=V2_SIGNAL_WEIGHTS)
    assert {r["rating"] for r in rows.values()} == {BASE}
```

- [ ] **Step 2: Run them and confirm they pass**

Run: `pytest tests/test_gm_rating_guards.py -v`
Expected: 4 passed

- [ ] **Step 3: Prove the additivity guard can fail**

Temporarily multiply `pillar_z` by `2.0` immediately before the `contribution` is computed in `compute_gm_ratings`, re-run, and confirm `test_signal_contributions_sum_to_their_pillar` goes red. **Revert the edit.** A guard nobody has seen fail is a guard nobody should trust.

- [ ] **Step 4: Commit**

```bash
git add tests/test_gm_rating_guards.py
git commit -m "test(engine): additivity, realized-weight and flat-league guards for the rating"
```

---

### Task 8: Cache schema bump and frozen-rollup placement

**Files:**
- Modify: `api/app/services/chain_cache.py:13`
- Modify: `api/app/services/grader.py` (the incremental reuse block)
- Test: `api/tests/services/test_grader_reuse_equivalence.py:27-35`

**Interfaces:**
- Consumes: the merged signal dicts (Task 5).
- Produces: `SCHEMA_VERSION = 17`.

**Placement rules, which v1's draft got half wrong:**
- `outcome_signals` is a **frozen rollup** — it describes seasons that are over. `expected_wins`, `playoff_success` and `luck` belong there and freeze correctly.
- `outlook_signals` is **not** frozen. `grader.py` deliberately omits it from the reuse block with the comment "stays freshly computed (current roster value/youth)". `roster_value_share` and `young_core_share` belong there and must keep recomputing — freezing them would stall roster value through the entire offseason, which is when dynasty value moves most.

- [ ] **Step 1: Write the failing test**

Add to `api/tests/services/test_grader_reuse_equivalence.py`:

```python
def test_outlook_signals_are_never_frozen():
    # Present-state signals must recompute on the incremental path. If
    # outlook_signals ever joins the reuse list, roster value freezes for the
    # whole offseason.
    assert "outlook_signals" not in FROZEN_FIELDS


def test_outcome_signals_are_frozen():
    assert "outcome_signals" in FROZEN_FIELDS
```

- [ ] **Step 2: Run it**

Run: `cd api && pytest tests/services/test_grader_reuse_equivalence.py -v`
Expected: PASS already if the constant is named `FROZEN_FIELDS`; if the test file enumerates the fields inline, extract them into a module-level `FROZEN_FIELDS` tuple first and have the existing test read it, then re-run.

- [ ] **Step 3: Bump the schema version**

In `api/app/services/chain_cache.py`:

```python
SCHEMA_VERSION = 17  # bumped: v2 Results/Assets signals (expected_wins reads 0.0 as a real value)
```

The bump is required rather than optional: `_raw` reads a missing key as `0.0`, and for `expected_wins` that means "lost every all-play matchup in every week" — a catastrophic wrong value, not an absent one. `chain_cache.py:146` returns `None` on a version mismatch, which forces a full rebuild and closes the hazard.

- [ ] **Step 4: Run the API suite**

Run: `cd api && pytest tests/ -q`
Expected: green.

- [ ] **Step 5: Commit**

```bash
git add api/app/services/chain_cache.py api/app/services/grader.py api/tests/services/test_grader_reuse_equivalence.py
git commit -m "feat(api): SCHEMA_VERSION 17 — v2 signals, with Assets left off the frozen list"
```

---

### Task 9: Snapshot model stamp

Existing rating snapshots carry no model identity, so after deploy the trend arrow diffs a v2 rating against a v1 one and shows a large phantom move that can persist for months (the offseason week key barely changes). Deleting the files is not enough — the R2 backup tars the cache volume, so a restore reintroduces them.

**Files:**
- Modify: `api/app/services/rating_snapshot_store.py`
- Test: `api/tests/services/test_rating_snapshot_store.py`

**Interfaces:**
- Consumes: `model` on each rating row (Task 6).
- Produces: `write(league_id, week_key, ratings, *, model: str)` and `latest_before(league_id, week_key, *, model: str)`, where keys are stored as `f"{model}:{week_key}"` and `latest_before` ignores keys whose model prefix differs.

- [ ] **Step 1: Write the failing test**

```python
def test_latest_before_ignores_a_different_model(tmp_path):
    store = RatingSnapshotStore(tmp_path)
    store.write("L", "2025-14", {"ua": 1600}, model="results_led")
    assert store.latest_before("L", "2026-01", model="v2_dynasty") == {}


def test_latest_before_finds_the_same_model(tmp_path):
    store = RatingSnapshotStore(tmp_path)
    store.write("L", "2026-01", {"ua": 1450}, model="v2_dynasty")
    assert store.latest_before("L", "2026-02", model="v2_dynasty") == {"ua": 1450}
```

- [ ] **Step 2: Run it**

Run: `cd api && pytest tests/services/test_rating_snapshot_store.py -v`
Expected: FAIL — `TypeError: write() got an unexpected keyword argument 'model'`

- [ ] **Step 3: Implement**

Prefix the stored week key with the model, and filter in `latest_before`. Update the two callers — `leaderboard.load_prev_ratings` and `aggregations._compute_gm_trends` — to pass the model from the rating rows. A trend with no same-model predecessor degrades to `None`, which the UI already renders as "—". That is the honest reading and it survives a restore.

- [ ] **Step 4: Run the API suite**

Run: `cd api && pytest tests/ -q`

- [ ] **Step 5: Commit**

```bash
git add api/app/services/rating_snapshot_store.py api/app/services/leaderboard.py api/app/services/aggregations.py api/tests/services/test_rating_snapshot_store.py
git commit -m "fix(api): stamp the model on rating snapshots so a v1 trend can't leak into v2"
```

---

### Task 10: Roster rank on the standings row

**Files:**
- Modify: `api/app/models/` (the `StandingRow` model), `api/app/services/aggregations.py`
- Test: `api/tests/services/test_aggregations_roster_rank.py` (create)

**Interfaces:**
- Consumes: `ChainCacheEntry.roster_ranks` (already persisted, `uid -> {"rank": int, "of": int}`).
- Produces: `StandingRow.roster_rank: int | None` and `StandingRow.roster_of: int | None`.

- [ ] **Step 1: Write the failing test**

```python
def test_standing_rows_carry_the_roster_rank(dynasty_entry):
    rows = build_standings(dynasty_entry)
    row = rows[0]
    assert row.roster_rank is not None
    assert row.roster_of == len(dynasty_entry.owners)


def test_redraft_leaves_roster_rank_absent(redraft_entry):
    # Absence, not a blank column - the same rule the Outlook columns follow.
    rows = build_standings(redraft_entry)
    assert all(r.roster_rank is None for r in rows)
```

- [ ] **Step 2: Run it** — `cd api && pytest tests/services/test_aggregations_roster_rank.py -v`. Expected FAIL: `AttributeError: 'StandingRow' object has no attribute 'roster_rank'`.

- [ ] **Step 3: Implement.** Add both fields to the Pydantic model with `= None` defaults, populate from `entry.roster_ranks` in `aggregations.py` beside where `gm_letter` is set, and gate on `_outlooks_apply` (already computed as `format != "redraft"`) so redraft rows stay `None`.

- [ ] **Step 4: Run** — `cd api && pytest tests/ -q`

- [ ] **Step 5: Commit**

```bash
git add api/app/models api/app/services/aggregations.py api/tests/services/test_aggregations_roster_rank.py
git commit -m "feat(api): roster rank on the standings row, absent for redraft"
```

---

### Task 11: The owner hero — blurb out, receipt in

This is the change that addresses the complaint that started the work: an unlabelled 48px letter with no receipt attached.

**Use the `furniture-styling` skill before writing any JSX here.**

**Files:**
- Modify: `web/components/ownerdeepdive/HeroBand.tsx`
- Modify: `web/components/ownerdeepdive/util.tsx` (add `biggestLever`)
- Test: `web/tests/HeroBand.test.tsx` (create)

**Interfaces:**
- Consumes: `OwnerDetailResp.roster_rank` (already on the type at `lib/types.ts:478`), `FranchiseRating` with `rating`, `rank`, `of`, `trend`, `pillars`.
- Produces: `biggestLever(fr: FranchiseRating): string | null` — the label of the signal with the largest `|weight × (league-best z − your z)|`.

- [ ] **Step 1: Write the failing test**

```tsx
it("renders the receipt under the letter", () => {
  render(<HeroBand detail={detailWithRating("B-", 1487, 6, 12)} rivalNames={[]} />);
  expect(screen.getByText("B-")).toBeTruthy();
  expect(screen.getByText(/ROSTER #6 OF 12/i)).toBeTruthy();
  expect(screen.getByText(/1,?487/)).toBeTruthy();
});

it("does not render the franchise blurb", () => {
  const detail = { ...detailWithRating("C", 1500, 6, 12),
                   franchise_blurb: "Despite a descending window..." };
  render(<HeroBand detail={detail} rivalNames={[]} />);
  expect(screen.queryByText(/descending window/i)).toBeNull();
});

it("keeps the rings strip", () => {
  render(<HeroBand detail={detailWithRating("C", 1500, 6, 12)} rivalNames={[]} />);
  expect(screen.getByText(/Playoff trips/i)).toBeTruthy();
});

it("omits the roster line when there is no roster rank", () => {
  const detail = { ...detailWithRating("C", 1500, 6, 12), roster_rank: null };
  render(<HeroBand detail={detail} rivalNames={[]} />);
  expect(screen.queryByText(/ROSTER #/i)).toBeNull();
});
```

- [ ] **Step 2: Run it** — `cd web && npx vitest --config tests/vitest.config.ts run tests/HeroBand.test.tsx`. Expected FAIL on the receipt assertions.

- [ ] **Step 3: Implement**

Delete the `detail.franchise_blurb` block at `HeroBand.tsx:133-134`. Extend `VerdictRail` to take `rosterRank` and render, right-aligned under the letter, in `font-mono text-label uppercase tracking-[0.11em] text-dim`:

- `ROSTER #{rank} OF {of}` — omitted entirely when `roster_rank` is null
- `{rating} {trend arrow}` — the existing `Trend` component, already declared in this file and currently unused
- `drag: {biggestLever(fr)}` — omitted when null

Replace the docstring above `VerdictRail`, which currently argues for removing exactly what this task restores. The new one should record why: the receipt's other home was one tab away, and a reader who cannot see it concludes the model is broken rather than going to look for it.

`biggestLever` goes in `util.tsx` beside the existing `ratingDrivers` (also currently imported by `HeroBand.tsx` and unused):

```tsx
/** The signal where this owner is furthest behind the league's best, scaled by
 *  what that signal is worth. Answers "what would move this most" — which turns
 *  a verdict you argue with into something you can act on. */
export function biggestLever(fr: FranchiseRating): string | null {
  let worst: { label: string; gap: number } | null = null;
  for (const p of Object.values(fr.pillars)) {
    for (const [k, s] of Object.entries(p.signals)) {
      const gap = Math.abs(p.weight * s.weight * s.z);
      if (s.z < 0 && (!worst || gap > worst.gap)) {
        worst = { label: SIGNAL_LABELS[k] ?? k, gap };
      }
    }
  }
  return worst?.label ?? null;
}
```

Add `SIGNAL_LABELS` entries for `expected_wins` ("Expected Wins"), `playoff_success` ("Playoff Success"), `luck` ("Close Games"), `roster_value_share` ("Roster Value"), `young_core_share` ("Young Core"), `draft_capital` ("Draft Capital"). A missing label falls through to the raw snake_case key and reaches the page.

- [ ] **Step 4: Run web tests** — `cd web && npx vitest --config tests/vitest.config.ts run`
- [ ] **Step 5: Commit**

```bash
git add web/components/ownerdeepdive/HeroBand.tsx web/components/ownerdeepdive/util.tsx web/tests/HeroBand.test.tsx
git commit -m "feat(web): the hero letter gets its receipt back and loses the blurb"
```

---

### Task 12: Retire the franchise-blurb writer

Task 11 removed the only render site in the app, so the generator now produces prose nobody reads. This is a straight LLM cost saving.

**Files:**
- Modify: `api/app/services/grader.py` (drop the franchise-blurb pass), the writer module under `src/sleeper_dynasty/llm/`, `api/app/services/owner_view.py`
- Test: `api/tests/services/test_owner_view.py`

- [ ] **Step 1: Write the failing test**

```python
def test_owner_view_no_longer_carries_a_franchise_blurb(dynasty_entry):
    view = build_owner_view(dynasty_entry, uid=next(iter(dynasty_entry.owners)))
    assert not hasattr(view, "franchise_blurb") or view.franchise_blurb is None
```

- [ ] **Step 2: Run it** — expected FAIL if a blurb is still populated.
- [ ] **Step 3:** Remove the generation pass and the `franchise_blurb` population. Leave `ChainCacheEntry.franchise_blurbs` on the dataclass — deleting a persisted field is a schema question and this is not the task for it; it simply stops being written. Remove `franchise_blurb` from the web `OwnerDetailResp` type.
- [ ] **Step 4: Run** — `cd api && pytest tests/ -q`
- [ ] **Step 5: Commit**

```bash
git commit -am "refactor: retire the franchise blurb, whose only render site is gone"
```

---

### Task 13: Roster rank columns on standings and the leaderboard

**Use the `furniture-styling` skill.**

**Files:**
- Modify: `web/components/StandingsTable.tsx`, `web/components/Leaderboard.tsx`, `web/lib/types.ts`
- Test: `web/tests/StandingsTable.test.tsx`

**Interfaces:**
- Consumes: `StandingRow.roster_rank` / `roster_of` (Task 10).

- [ ] **Step 1: Write the failing test**

```tsx
it("renders a Roster column when the rows carry a rank", () => {
  render(<StandingsTable rows={[row({ roster_rank: 6, roster_of: 12 })]} />);
  expect(screen.getByText("Roster")).toBeTruthy();
  expect(screen.getByText("#6")).toBeTruthy();
});

it("omits the Roster column entirely for redraft", () => {
  render(<StandingsTable rows={[row({ roster_rank: null, roster_of: null })]} />);
  expect(screen.queryByText("Roster")).toBeNull();
});
```

- [ ] **Step 2: Run it** — `cd web && npx vitest --config tests/vitest.config.ts run tests/StandingsTable.test.tsx`
- [ ] **Step 3:** Add `roster_rank`/`roster_of` to the TS types as `?: number | null`. Add a `hasRosterColumn` gate mirroring the existing `hasOutlookColumns`, and render `#{rank}` in a new column. Do the same on the `/gm` leaderboard.
- [ ] **Step 4: Run** — `cd web && npx vitest --config tests/vitest.config.ts run`
- [ ] **Step 5: Commit**

```bash
git add web/components/StandingsTable.tsx web/components/Leaderboard.tsx web/lib/types.ts web/tests/StandingsTable.test.tsx
git commit -m "feat(web): roster rank column on standings and the leaderboard"
```

---

### Task 14: Two latent web bugs the split makes live

**Files:**
- Modify: `web/components/Leaderboard.tsx:385`, `web/components/OwnersTab.tsx:127`
- Test: `web/tests/Leaderboard.test.tsx`, `web/tests/OwnersTab.test.tsx`

- [ ] **Step 1: Write the failing tests**

```tsx
it("detects redraft from the capabilities format, not a missing pillar", () => {
  // After v2 NO tree has an `outlook` pillar, so `"outlook" in r.pillars` is
  // permanently false and every league would read as redraft.
  render(<Leaderboard rows={[gmRow({ model: "v2_dynasty" })]} format="dynasty" />);
  expect(screen.queryByText(/two pillars/i)).toBeNull();
});

it("never falls back to the trade grade for a missing franchise letter", () => {
  // gm_letter ?? grade renders the net-value trade grade in identical styling,
  // so the two verdicts become indistinguishable.
  render(<OwnersTab owners={[owner({ gm_letter: null, grade: "A" })]} />);
  expect(screen.queryByText("A")).toBeNull();
  expect(screen.getByText("—")).toBeTruthy();
});
```

- [ ] **Step 2: Run them** — both fail.
- [ ] **Step 3:** Replace the pillar-presence check with the league's capabilities format, threaded from the dashboard response. Replace `o.gm_letter ?? o.grade` with `o.gm_letter ?? null`, rendering an em dash when absent.
- [ ] **Step 4: Run** — `cd web && npx vitest --config tests/vitest.config.ts run`
- [ ] **Step 5: Commit**

```bash
git commit -am "fix(web): redraft detection by format, and stop the trade grade masquerading as the franchise letter"
```

---

### Task 15: The methodology page

It is the only surface that explains the grade, and on deploy it will be actively lying. It hand-copies `LETTER_BANDS` into TypeScript with no import and no cross-language test, hardcodes the old pillar weights, and publishes a promise that recency decay reverses.

**Files:**
- Modify: `web/components/methodology/MethodologyContent.tsx`, `web/components/methodology/sample.ts`
- Test: `web/tests/methodology-bands.test.ts` (create)

- [ ] **Step 1: Write the failing test**

```ts
import { LETTER_BANDS as UI_BANDS } from "@/components/methodology/MethodologyContent";
import bands from "../../.generated/letter-bands.json";

it("the published band table matches the engine's", () => {
  expect(UI_BANDS).toEqual(bands);
});
```

Generate `web/.generated/letter-bands.json` from the engine in a small script run as part of the build, so the hand-copy can never drift again. If a generated artifact is too much machinery for this repo's conventions, the fallback is to assert the exact expected array inline — worse, but still a test that fails when the engine moves.

- [ ] **Step 2: Run it** — fails on the stale table.
- [ ] **Step 3:** Update the bands, the weights (`0.60 Results / 0.40 Assets`), and the per-signal prose. Replace the promise *"not year-scoped, so a one-year blip doesn't whipsaw your letter"* — it is now false. Add three statements v2 makes true:
  - the letter is a **percentile within your league**, not an absolute standard;
  - the scale runs **A+ to D−**, and why there is no F;
  - the two-season half-life is a **chosen prior**, not a measured one — lag-2 ≈ lag-1² is a real AR(1) signature, but the half-life cannot be estimated from three seasons of twelve owners.
- [ ] **Step 4: Run** — `cd web && npx vitest --config tests/vitest.config.ts run`
- [ ] **Step 5: Commit**

```bash
git add web/components/methodology web/tests/methodology-bands.test.ts
git commit -m "docs(web): methodology describes v2, and the band table stops being a hand-copy"
```

---

### Task 16: Blurb pillar keys

**Files:**
- Modify: `src/sleeper_dynasty/llm/gm_rating_blurb_writer.py:27`, `src/sleeper_dynasty/llm/prompts/gm_rating_blurb_persona.md`, `src/sleeper_dynasty/engine/gm_rating_blurb.py:10-26`, `api/app/services/blurb_gen.py`
- Test: `tests/test_gm_rating_blurb_facts.py`

- [ ] **Step 1: Write the failing test**

```python
def test_pillar_keys_are_the_v2_pair():
    assert _PILLAR_KEYS == {"Results", "Assets"}


def test_every_v2_signal_has_a_label():
    for sig in ("expected_wins", "playoff_success", "luck",
                "roster_value_share", "young_core_share", "draft_capital"):
        assert sig in SIGNAL_LABELS
        assert SIGNAL_LABELS[sig] != sig
```

- [ ] **Step 2: Run it** — fails.
- [ ] **Step 3:** Change `_PILLAR_KEYS` to `{"Results", "Assets"}`, update `PILLAR_LABELS` / `SIGNAL_LABELS` / `_PILLAR_ORDER`, rewrite the persona's three-key requirement and its "close on Outlook or Skill" phrasing, and bump `BLURB_PROMPT_VERSION` so every cached blurb regenerates. Redraft emits `{"Results"}` only.
- [ ] **Step 4: Run** — `pytest tests/ -q && cd api && pytest tests/ -q`
- [ ] **Step 5: Commit**

```bash
git commit -am "feat(llm): blurb pillars follow the v2 tree; prompt version bumped"
```

---

### Task 17: Calibrate and record

**Use the `franchise-rating-calibration` skill.**

**Files:**
- Modify: `src/sleeper_dynasty/engine/gm_rating.py` (`REFERENCE_COMPOSITE_SD`)
- Modify: `docs/superpowers/specs/2026-08-16-franchise-rating-v2-design.md` (record the result)

- [ ] **Step 1: Force-refresh the reference league** so the cache is rebuilt at `SCHEMA_VERSION` 17 with the v2 signals present.
- [ ] **Step 2: Run the harness** from the skill: load the chain entry, run `live_ratings`, and print the full-league table plus the composite sd.
- [ ] **Step 3: Set `REFERENCE_COMPOSITE_SD`** to the measured value and re-run.
- [ ] **Step 4: Check the distribution.** Letters must span at least five distinct values across twelve owners, and no owner may fall below D−. If the spread is degenerate in either direction, adjust `_BAND_SD` — not the pillar weights, which are a product decision and not a calibration knob.
- [ ] **Step 5: Record** the table and the measured sd in the spec's "Prototype result" section, replacing the v1 numbers, and commit both files together.

```bash
git add src/sleeper_dynasty/engine/gm_rating.py docs/superpowers/specs/2026-08-16-franchise-rating-v2-design.md
git commit -m "chore(engine): calibrate SCALE against the reference league and record the distribution"
```

---

## Self-Review

**Spec coverage.** Results trio → Tasks 1, 2, 5. Assets → Tasks 3, 5. Recency and the decay clamp → Task 2. Trees, SCALE, bands, no-F, C+ restored → Task 4. No re-standardization / no shrinkage → satisfied by omission, guarded in Task 7. Persistence and placement → Task 8. Snapshots → Task 9. Hero → Tasks 11, 12. Roster rank → Tasks 10, 13. Format trees → Task 4 (weights) and Task 6 (selection). Methodology → Task 15. Blurbs → Task 16. Validation → Task 7 plus Task 17.

**Two spec items deliberately not tasked here.** The thin-evidence gate (render `—` for a league with no played season, and for an owner in their first) needs a UI decision per surface and is a follow-on; `latest_played_season` already returns `None` for that case, which is the hook it will use. And `engine/gm_signals.outlook_signals` — dead code with no production caller, still exercised by `tests/test_gm_signals.py` — should be deleted during Task 5 while that file is open.

**Type consistency.** `all_play_win_pct` returns uid-keyed in Task 1 and is consumed uid-keyed in Task 5. `results_signals` and `asset_signals` both return `dict[str, dict[str, float]]` and are merged into the persisted dicts under the exact keys Task 6's `build_v2_pillars` reads: `expected_wins`, `playoff_success`, `luck`, `roster_value_share`, `young_core_share`, `draft_capital`. Those same six strings are the labels asserted in Task 16 and the `SIGNAL_LABELS` keys added in Task 11.
