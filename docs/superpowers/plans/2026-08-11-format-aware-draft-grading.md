# Format-Aware Draft Grading Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Grade every league's yearly draft correctly — dynasty rookie drafts, redraft full drafts, and keeper drafts — against three separate baselines, with a league-wide draft board that renders results on draft night and layers grades in as the season plays out.

**Architecture:** Each Sleeper draft is normalized once at ingestion into a `DraftClass` descriptor carrying its kind, gradeability, and grading axis, so format branching happens at one boundary instead of being re-derived at every call site. Grading produces three independent readings — a league-native peer delta, an ADP delta, and a projection delta — rather than one blended composite. Only the peer delta feeds Franchise Rating, because it is the sole baseline available in every format.

**Tech Stack:** Python 3 / FastAPI / pytest (engine + API), Next.js 14 App Router / React / Tailwind / vitest (web). Sleeper HTTP API. No new dependencies.

## Global Constraints

- **Never render "KTC" in the UI.** It is "Trade Value" / "Value". `web/tests/agate-rules.test.ts` fails the build on a rendered "KTC".
- **All new UI follows the Agate design system.** Invoke the `agate-styling` skill before writing any component. No `rounded-`, `shadow-`, `animate-pulse`, `backdrop-blur`, `lucide`, `sticky`, `overflow-x-auto`, or `divide-y` in `web/{app,components,lib}`.
- **`999.0` is Sleeper's undrafted ADP sentinel.** Always filter `>= 999` before use. An unfiltered sentinel becomes a catch-all bucket.
- **Metric vocabulary is fixed:** Trade Value / Total Points / Regular Season Points / Playoff Points / Toilet Bowl Points.
- **Engine modules are pure.** No I/O in `src/sleeper_dynasty/engine/`. Callers thread in fetched data.
- **Refresh stages degrade, never fail.** Any external fetch failure logs and drops its columns; the peer baseline carries the board.
- **`draft_skill` feeding Franchise Rating stays the peer baseline in every format.** ADP and projection deltas are board-facing only and must never reach the rating. Do not change `SIGNAL_WEIGHTS` or `REDESIGN_SIGNAL_WEIGHTS`. Note the distinction: the *peer baseline* is the comparison method (a pick vs its round/tier peers) and never changes; the *axis* is what the outcome is measured on (value+production for dynasty, production alone for redraft/keeper) and does change by format. Changing the axis is in scope; swapping in an ADP-derived rating input is not.
- **Engine tests:** `pytest tests/` from repo root. Bare `pytest` breaks (two packages named `tests`).
- **Frontend tests:** `cd web && npx vitest --config tests/vitest.config.ts run`. Bare `npx vitest run` silently uses no config and fails on JSX.
- **Spec of record:** `docs/superpowers/specs/2026-08-11-format-aware-draft-grading-design.md`.

---

## File Structure

**Create:**
- `src/sleeper_dynasty/engine/draft_class.py` — `DraftClass` descriptor + draft/pick normalization. Owns all format branching.
- `src/sleeper_dynasty/engine/draft_baselines.py` — pure ADP/projection parsing and delta math.
- `api/app/services/adp_snapshot_store.py` — write-once draft-day ADP capture, keyed by `draft_id`.
- `api/app/routes/draft.py` — the league-wide draft board endpoint.
- `api/app/services/draft_board_view.py` — assembles the board response.
- `web/app/league/[id]/draft/[season]/page.tsx` — the board page.
- `web/components/DraftBoard.tsx` — the board table.
- `tests/test_draft_class.py`, `tests/test_draft_baselines.py`, `api/tests/test_adp_snapshot_store.py`, `api/tests/test_draft_board_view.py`, `web/tests/draft-board.test.tsx`

**Modify:**
- `src/sleeper_dynasty/engine/draft_signals.py` — `DraftedPick` gains fields; `draft_skill` gains keeper filtering + axis.
- `src/sleeper_dynasty/engine/draft_results.py` — per-pick rows gain ADP/projection fields; `build_draft_review` gains the ungraded state.
- `api/app/services/grader.py` — wire `DraftClass`, fetch projections, capture snapshot.
- `api/app/services/rating_signals.py` — pass axis through to `draft_skill`.
- `api/app/models/league.py` — `DraftReview` gains `graded`; `best`/`worst` become optional.
- `api/app/services/aggregations.py` — `_draft_review` handles the ungraded state.
- `api/app/services/owner_view.py` — no change needed; gating fix is frontend-side.
- `web/components/OwnerDeepDive.tsx` — Draft tab gated on picks, not outlook.
- `web/components/ownerdeepdive/FutureDraftTab.tsx` — `PastPicksTable` moves out.
- `web/components/ownerdeepdive/PastPicksTable.tsx` — keeper chip, format-aware columns.
- `web/components/HeadlineMoves.tsx` — pre/post-draft lead source.
- `web/lib/types.ts` — new response types.
- `CLAUDE.md` — document the new draft-grading contract.

---

## Phase 1 — Engine (pure, no I/O)

### Task 1: `DraftClass` normalization

**Files:**
- Create: `src/sleeper_dynasty/engine/draft_class.py`
- Create: `tests/test_draft_class.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces: `DraftClass` dataclass with fields `draft_id: str`, `league_id: str`, `season: int`, `kind: str`, `draft_type: str`, `teams: int`, `gradeable: bool`, `axis: str`. Functions `build_draft_classes(*, drafts_by_league: dict[str, list[dict]], league_format: str, origin_season: int) -> list[DraftClass]` and `build_draft_picks(*, classes: list[DraftClass], picks_by_draft_id: dict[str, list[dict]], roster_to_user_by_league: dict[str, dict[int, str]]) -> list[DraftedPick]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_draft_class.py`:

```python
import pytest

from sleeper_dynasty.engine.draft_class import (
    DraftClass, build_draft_classes, build_draft_picks,
)


def _draft(draft_id, season, player_type, *, league_id="lg", status="complete",
           dtype="snake", teams=12):
    return {
        "draft_id": draft_id, "league_id": league_id, "season": str(season),
        "status": status, "type": dtype,
        "settings": {"rounds": 4, "teams": teams, "player_type": player_type},
    }


# --- format selection ---

def test_dynasty_keeps_rookie_drafts_and_drops_the_startup():
    drafts = {"lg": [_draft("d_start", 2022, 0), _draft("d_rook", 2023, 1)]}
    out = build_draft_classes(
        drafts_by_league=drafts, league_format="dynasty", origin_season=2022)
    assert [c.draft_id for c in out] == ["d_rook"]
    assert out[0].kind == "rookie"
    assert out[0].axis == "blend"


def test_dynasty_keeps_a_rookie_draft_held_in_the_origin_season():
    """A league that ran a startup AND a rookie draft in year one keeps the
    rookie class — player_type discriminates, the season no longer does."""
    drafts = {"lg": [_draft("d_start", 2022, 0), _draft("d_rook", 2022, 1)]}
    out = build_draft_classes(
        drafts_by_league=drafts, league_format="dynasty", origin_season=2022)
    assert [c.draft_id for c in out] == ["d_rook"]


def test_redraft_keeps_every_full_draft_including_year_one():
    drafts = {"lg": [_draft("d1", 2024, 0), _draft("d2", 2025, 0)]}
    out = build_draft_classes(
        drafts_by_league=drafts, league_format="redraft", origin_season=2024)
    assert [c.draft_id for c in out] == ["d1", "d2"]
    assert all(c.kind == "full" for c in out)
    assert all(c.axis == "production" for c in out)


def test_keeper_grades_on_production_like_redraft():
    drafts = {"lg": [_draft("d1", 2024, 0)]}
    out = build_draft_classes(
        drafts_by_league=drafts, league_format="keeper", origin_season=2024)
    assert out[0].axis == "production"
    assert out[0].kind == "full"


def test_incomplete_drafts_are_excluded():
    drafts = {"lg": [_draft("d1", 2025, 1, status="drafting")]}
    assert build_draft_classes(
        drafts_by_league=drafts, league_format="dynasty", origin_season=2024) == []


def test_auction_is_ingested_but_not_gradeable():
    drafts = {"lg": [_draft("d1", 2025, 0, dtype="auction")]}
    out = build_draft_classes(
        drafts_by_league=drafts, league_format="redraft", origin_season=2025)
    assert out[0].gradeable is False
    assert out[0].draft_type == "auction"


def test_missing_player_type_falls_back_to_the_origin_season_heuristic():
    """Older Sleeper drafts may not carry player_type. Dynasty then falls back
    to the previous rule rather than silently grading the startup."""
    d_start = _draft("d_start", 2022, 0)
    d_late = _draft("d_late", 2023, 0)
    for d in (d_start, d_late):
        del d["settings"]["player_type"]
    out = build_draft_classes(
        drafts_by_league={"lg": [d_start, d_late]},
        league_format="dynasty", origin_season=2022)
    assert [c.draft_id for c in out] == ["d_late"]


# --- pick normalization ---

def _cls(draft_id="d1", season=2025, kind="full", teams=12, axis="production"):
    return DraftClass(
        draft_id=draft_id, league_id="lg", season=season, kind=kind,
        draft_type="snake", teams=teams, gradeable=True, axis=axis)


def test_picks_carry_kind_keeper_flag_and_overall_pick_number():
    picks = {"d1": [
        {"round": 1, "draft_slot": 1, "pick_no": 1, "player_id": "p1",
         "picked_by": "u1", "is_keeper": None},
        {"round": 2, "draft_slot": 3, "pick_no": 15, "player_id": "p2",
         "picked_by": "u2", "is_keeper": True},
    ]}
    out = build_draft_picks(
        classes=[_cls()], picks_by_draft_id=picks, roster_to_user_by_league={})
    assert [p.player_id for p in out] == ["p1", "p2"]
    assert out[0].is_keeper is False
    assert out[1].is_keeper is True
    assert out[0].draft_kind == "full"
    assert out[1].pick_no == 15


def test_pick_number_is_derived_when_sleeper_omits_it():
    picks = {"d1": [
        {"round": 2, "draft_slot": 1, "player_id": "p1", "picked_by": "u1"},
    ]}
    out = build_draft_picks(
        classes=[_cls(teams=12)], picks_by_draft_id=picks,
        roster_to_user_by_league={})
    assert out[0].pick_no == 13


def test_drafter_falls_back_to_the_slot_rosters_current_owner():
    picks = {"d1": [
        {"round": 1, "draft_slot": 1, "pick_no": 1, "player_id": "p1",
         "picked_by": None, "roster_id": 4},
    ]}
    out = build_draft_picks(
        classes=[_cls()], picks_by_draft_id=picks,
        roster_to_user_by_league={"lg": {4: "u9"}})
    assert out[0].drafter_id == "u9"


def test_picks_without_a_player_or_drafter_are_dropped():
    picks = {"d1": [
        {"round": 1, "draft_slot": 1, "pick_no": 1, "player_id": None,
         "picked_by": "u1"},
        {"round": 1, "draft_slot": 2, "pick_no": 2, "player_id": "p2",
         "picked_by": None},
    ]}
    out = build_draft_picks(
        classes=[_cls()], picks_by_draft_id=picks, roster_to_user_by_league={})
    assert out == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_draft_class.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sleeper_dynasty.engine.draft_class'`

- [ ] **Step 3: Write the implementation**

Create `src/sleeper_dynasty/engine/draft_class.py`:

```python
"""Draft normalization: what each Sleeper draft *is*, decided once.

Every format question about a draft — is this a rookie class or a full
draft, can it be graded, what does it get graded against — is answered here
and nowhere else. Downstream consumers read the descriptor rather than
re-deriving the answer, which is what stops "is this dynasty?" from being
asked in five places and drifting apart.

Pure. No I/O — callers thread in the draft and pick payloads.
"""

from __future__ import annotations

from dataclasses import dataclass

from sleeper_dynasty.engine.draft_signals import DraftedPick

# Sleeper's draft setting: 1 = rookies only, 0 = all players. Verified live
# against a real dynasty rookie draft (player_type == 1).
_ROOKIE_ONLY = 1

# Formats whose graded event is the whole-league draft, every season.
_FULL_DRAFT_FORMATS = {"redraft", "keeper"}

# An auction's pick_no is chronological, not positional, so a slot delta
# would be noise. Ingested for results, never graded.
_UNGRADEABLE_TYPES = {"auction"}


@dataclass(frozen=True)
class DraftClass:
    """One completed draft, described in format-neutral terms."""

    draft_id: str
    league_id: str
    season: int
    kind: str        # "rookie" | "full"
    draft_type: str  # "snake" | "linear" | "auction"
    teams: int
    gradeable: bool  # False for auction — results only
    axis: str        # "blend" (value + production) | "production"


def build_draft_classes(
    *,
    drafts_by_league: dict[str, list[dict]],
    league_format: str,
    origin_season: int,
) -> list[DraftClass]:
    """Select and describe the drafts this league's format actually grades.

    Dynasty grades rookie classes and discards the startup. Redraft and keeper
    grade every season's full draft, *including year one* — there is no
    "startup" in a league that redrafts from scratch annually.

    Selection keys on ``settings.player_type`` rather than the season, so a
    dynasty league that ran a startup and a rookie draft in the same origin
    season keeps the rookie class. When ``player_type`` is absent (older
    drafts), dynasty falls back to the origin-season heuristic rather than
    grading what is probably a startup.
    """
    full_draft_league = league_format in _FULL_DRAFT_FORMATS
    axis = "production" if full_draft_league else "blend"

    out: list[DraftClass] = []
    for league_id, drafts in drafts_by_league.items():
        for d in drafts:
            if d.get("status") != "complete":
                continue
            settings = d.get("settings") or {}
            season = int(d.get("season") or 0)
            player_type = settings.get("player_type")

            if player_type is None:
                # No discriminator available: dynasty falls back to the old
                # "the origin season is the startup" rule.
                if not full_draft_league and season == origin_season:
                    continue
                kind = "full" if full_draft_league else "rookie"
            else:
                is_rookie_class = int(player_type) == _ROOKIE_ONLY
                if not full_draft_league and not is_rookie_class:
                    continue  # dynasty startup
                kind = "rookie" if is_rookie_class else "full"

            draft_type = str(d.get("type") or "snake")
            out.append(DraftClass(
                draft_id=str(d["draft_id"]),
                league_id=league_id,
                season=season,
                kind=kind,
                draft_type=draft_type,
                teams=int(settings.get("teams") or 0),
                gradeable=draft_type not in _UNGRADEABLE_TYPES,
                axis=axis,
            ))
    return out


def build_draft_picks(
    *,
    classes: list[DraftClass],
    picks_by_draft_id: dict[str, list[dict]],
    roster_to_user_by_league: dict[str, dict[int, str]],
) -> list[DraftedPick]:
    """Normalize each class's picks into ``DraftedPick`` rows.

    Credits ``picked_by``, falling back to the slot roster's current owner.
    A pick with neither a player nor a resolvable drafter is dropped — there
    is nothing to grade and a placeholder would pollute the peer baseline.
    """
    out: list[DraftedPick] = []
    for cls in classes:
        r2u = roster_to_user_by_league.get(cls.league_id, {})
        teams = cls.teams or len(r2u) or 1
        for pk in picks_by_draft_id.get(cls.draft_id, []):
            player_id = pk.get("player_id")
            if not player_id:
                continue
            drafter = pk.get("picked_by") or r2u.get(pk.get("roster_id"))
            if not drafter:
                continue
            rnd = int(pk.get("round") or 1)
            slot = int(pk.get("draft_slot") or 0)
            # Sleeper sends pick_no, but derive it when absent so the overall
            # position is always available for ADP comparison.
            pick_no = int(pk.get("pick_no") or ((rnd - 1) * teams + slot))
            out.append(DraftedPick(
                draft_id=cls.draft_id,
                round=rnd,
                slot=slot,
                picks_in_round=teams,
                player_id=str(player_id),
                drafter_id=str(drafter),
                draft_season=cls.season,
                pick_no=pick_no,
                draft_kind=cls.kind,
                is_keeper=bool(pk.get("is_keeper")),
            ))
    return out
```

- [ ] **Step 4: Add the new `DraftedPick` fields**

Modify `src/sleeper_dynasty/engine/draft_signals.py`, replacing the `DraftedPick` dataclass:

```python
@dataclass
class DraftedPick:
    draft_id: str
    round: int
    slot: int            # 1-based position within the round
    picks_in_round: int
    player_id: str
    drafter_id: str      # owner uid who made the selection
    draft_season: int = 0  # NFL season year of the draft (0 = unknown)
    pick_no: int = 0     # overall pick number, 1-based (round 2 slot 1 = 13)
    draft_kind: str = "rookie"  # "rookie" | "full"
    is_keeper: bool = False     # kept, not drafted — shown but never scored
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/test_draft_class.py -v`
Expected: PASS (12 tests)

- [ ] **Step 6: Verify nothing else broke**

Run: `pytest tests/ -q`
Expected: PASS — `build_rookie_picks` is still present and untouched; the new fields all have defaults.

- [ ] **Step 7: Commit**

```bash
git add src/sleeper_dynasty/engine/draft_class.py \
        src/sleeper_dynasty/engine/draft_signals.py \
        tests/test_draft_class.py
git commit -m "feat(engine): DraftClass normalizes drafts per league format"
```

---

### Task 2: Keeper exclusion and the production axis in `draft_skill`

**Files:**
- Modify: `src/sleeper_dynasty/engine/draft_signals.py:131-199`
- Modify: `tests/test_draft_signals.py`

**Interfaces:**
- Consumes: `DraftedPick` with `is_keeper` and `draft_kind` from Task 1.
- Produces: `draft_skill(..., axis: str = "blend") -> dict[str, float]`, unchanged return shape (uid → shrunk skill score).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_draft_signals.py`:

```python
# --- keeper exclusion + grading axis ---

def _pick(pid, uid, *, rnd=1, slot=1, keeper=False, draft_id="d1", teams=4):
    return DraftedPick(
        draft_id=draft_id, round=rnd, slot=slot, picks_in_round=teams,
        player_id=pid, drafter_id=uid, draft_season=2025,
        pick_no=(rnd - 1) * teams + slot, draft_kind="full", is_keeper=keeper)


def test_keeper_picks_do_not_score_for_their_owner():
    picks = [
        _pick("p1", "u1", slot=1), _pick("p2", "u2", slot=2),
        _pick("p3", "u3", slot=3), _pick("p4", "u4", slot=4),
    ]
    ktc = {"p1": 100.0, "p2": 50.0, "p3": 50.0, "p4": 50.0}
    prod = {"p1": 100.0, "p2": 50.0, "p3": 50.0, "p4": 50.0}
    graded = draft_skill(picks=picks, ktc_by_player=ktc, production_by_player=prod)
    assert graded["u1"] > 0  # baseline: a strong pick scores

    picks[0] = _pick("p1", "u1", slot=1, keeper=True)
    kept = draft_skill(picks=picks, ktc_by_player=ktc, production_by_player=prod)
    assert "u1" not in kept


def test_keeper_picks_do_not_drag_the_peer_baseline():
    """A kept star in round 1 must not raise what round 1 is expected to
    return, which would unfairly penalise everyone who actually picked."""
    others = [_pick("p2", "u2", slot=2), _pick("p3", "u3", slot=3),
              _pick("p4", "u4", slot=4)]
    ktc = {"p1": 1000.0, "p2": 50.0, "p3": 50.0, "p4": 50.0}
    prod = {"p1": 1000.0, "p2": 50.0, "p3": 50.0, "p4": 50.0}

    without = draft_skill(
        picks=others, ktc_by_player=ktc, production_by_player=prod)
    with_keeper = draft_skill(
        picks=[_pick("p1", "u1", slot=1, keeper=True)] + others,
        ktc_by_player=ktc, production_by_player=prod)
    assert with_keeper["u2"] == pytest.approx(without["u2"])


def test_production_axis_ignores_value_entirely():
    """Redraft: two picks identical on production, wildly different on value.
    Under the production axis they must grade the same."""
    picks = [_pick("p1", "u1", slot=1), _pick("p2", "u2", slot=2)]
    prod = {"p1": 100.0, "p2": 100.0}
    ktc = {"p1": 5000.0, "p2": 0.0}
    out = draft_skill(
        picks=picks, ktc_by_player=ktc, production_by_player=prod,
        axis="production")
    assert out["u1"] == pytest.approx(out["u2"])


def test_production_axis_still_separates_on_production():
    picks = [_pick("p1", "u1", slot=1), _pick("p2", "u2", slot=2)]
    out = draft_skill(
        picks=picks, ktc_by_player={"p1": 0.0, "p2": 0.0},
        production_by_player={"p1": 300.0, "p2": 10.0}, axis="production")
    assert out["u1"] > out["u2"]


def test_production_axis_does_not_exempt_unplayed_picks():
    """Under the blend axis an unplayed rookie is judged on value alone. In
    redraft a pick that never played scored nothing, and that is the answer."""
    picks = [_pick("p1", "u1", slot=1), _pick("p2", "u2", slot=2)]
    out = draft_skill(
        picks=picks, ktc_by_player={"p1": 5000.0, "p2": 0.0},
        production_by_player={"p1": 0.0, "p2": 200.0},
        games_by_player={"p1": 0, "p2": 17}, axis="production")
    assert out["u2"] > out["u1"]


def test_blend_axis_is_unchanged_for_dynasty():
    picks = [_pick("p1", "u1", slot=1), _pick("p2", "u2", slot=2)]
    ktc = {"p1": 100.0, "p2": 0.0}
    prod = {"p1": 0.0, "p2": 0.0}
    explicit = draft_skill(
        picks=picks, ktc_by_player=ktc, production_by_player=prod, axis="blend")
    default = draft_skill(
        picks=picks, ktc_by_player=ktc, production_by_player=prod)
    assert explicit == default


def test_all_keeper_class_grades_nobody():
    picks = [_pick("p1", "u1", slot=1, keeper=True),
             _pick("p2", "u2", slot=2, keeper=True)]
    assert draft_skill(
        picks=picks, ktc_by_player={}, production_by_player={}) == {}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_draft_signals.py -v -k "keeper or axis"`
Expected: FAIL — `draft_skill() got an unexpected keyword argument 'axis'`

- [ ] **Step 3: Write the implementation**

In `src/sleeper_dynasty/engine/draft_signals.py`, replace the body of `draft_skill` from its signature through the `outcome` computation:

```python
def draft_skill(
    *,
    picks: list[DraftedPick],
    ktc_by_player: dict[str, float],
    production_by_player: dict[str, float],
    games_by_player: dict[str, int] | None = None,
    min_games: int = 17,
    shrink_k: float = 3.0,
    axis: str = "blend",
) -> dict[str, float]:
    """Per-owner drafting skill: each pick's outcome minus the average outcome
    of its (draft, round, tier) peers, averaged over the owner's picks with
    small-sample shrinkage. Owners with no graded picks are absent.

    ``axis`` selects what "outcome" means:

    - "blend" (dynasty rookie drafts): value and production, 50/50. When
      ``games_by_player`` is provided a pick is "played" iff the player logged
      ``>= min_games`` game-weeks with points > 0; unplayed picks are judged on
      value alone so rookies who have not had a full season are not penalised
      for missing points. Production z-scores are computed over played picks
      only.
    - "production" (redraft and keeper full drafts): production alone. There is
      no unplayed carve-out — a redraft pick that never played scored nothing,
      and that is the real answer rather than missing data. Value is ignored
      entirely, because these leagues have no price history behind it.

    **Keeper picks are excluded outright.** A keep is not a draft decision, and
    leaving one in the peer group would raise what its round is expected to
    return, penalising everyone who actually picked there.
    """
    picks = [p for p in picks if not p.is_keeper]
    if not picks:
        return {}

    if axis == "production":
        outcome = _zscores(
            [float(production_by_player.get(p.player_id, 0.0)) for p in picks])
    else:
        zk = _zscores([float(ktc_by_player.get(p.player_id, 0.0)) for p in picks])
        if games_by_player is None:
            zp = _zscores(
                [float(production_by_player.get(p.player_id, 0.0)) for p in picks])
            outcome = [0.5 * zk[i] + 0.5 * zp[i] for i in range(len(picks))]
        else:
            played = [
                int(games_by_player.get(p.player_id, 0)) >= min_games for p in picks
            ]
            played_indices = [i for i, is_played in enumerate(played) if is_played]
            played_prods = [
                float(production_by_player.get(picks[i].player_id, 0.0))
                for i in played_indices
            ]
            played_zp = _zscores(played_prods)
            zp_by_idx: dict[int, float] = {
                played_indices[k]: played_zp[k] for k in range(len(played_indices))
            }
            outcome = []
            for i in range(len(picks)):
                if played[i]:
                    outcome.append(0.5 * zk[i] + 0.5 * zp_by_idx[i])
                else:
                    outcome.append(zk[i])
```

Leave everything from `tier_groups: dict[tuple, list[int]] = defaultdict(list)` onward exactly as it is.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_draft_signals.py -v`
Expected: PASS — new tests pass and every pre-existing `draft_skill` test still passes (the blend path is byte-identical).

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/draft_signals.py tests/test_draft_signals.py
git commit -m "feat(engine): exclude keepers from draft skill, add production axis"
```

---

### Task 3: ADP and projection baselines

**Files:**
- Create: `src/sleeper_dynasty/engine/draft_baselines.py`
- Create: `tests/test_draft_baselines.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (pure math over raw Sleeper payloads).
- Produces: `ADP_UNDRAFTED: float`, `adp_field_for(*, rec_points: float, superflex: bool) -> str`, `points_field_for(*, rec_points: float) -> str`, `parse_adp(raw: dict, *, field: str) -> dict[str, float]`, `parse_projected_points(raw: dict, *, field: str) -> dict[str, float]`, `adp_delta(*, pick_no: int, adp: float | None) -> float | None`, `owner_adp_grades(rows: list[dict]) -> dict[str, dict]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_draft_baselines.py`:

```python
import pytest

from sleeper_dynasty.engine.draft_baselines import (
    ADP_UNDRAFTED, adp_delta, adp_field_for, owner_adp_grades, parse_adp,
    parse_projected_points, points_field_for,
)


# --- scoring-format field selection ---

def test_superflex_wins_over_reception_scoring():
    assert adp_field_for(rec_points=1.0, superflex=True) == "adp_2qb"


def test_ppr_half_and_standard_map_to_their_own_fields():
    assert adp_field_for(rec_points=1.0, superflex=False) == "adp_ppr"
    assert adp_field_for(rec_points=0.5, superflex=False) == "adp_half_ppr"
    assert adp_field_for(rec_points=0.0, superflex=False) == "adp_std"


def test_points_field_has_no_superflex_variant():
    assert points_field_for(rec_points=1.0) == "pts_ppr"
    assert points_field_for(rec_points=0.5) == "pts_half_ppr"
    assert points_field_for(rec_points=0.0) == "pts_std"


# --- parsing ---

def test_undrafted_sentinel_is_filtered_out():
    """999.0 means 'never drafted', not 'drafted 999th'. Left in, it becomes a
    catch-all bucket that silently grades every undrafted player identically."""
    raw = {"p1": {"adp_ppr": 12.5}, "p2": {"adp_ppr": ADP_UNDRAFTED}}
    assert parse_adp(raw, field="adp_ppr") == {"p1": 12.5}


def test_missing_and_non_numeric_values_are_skipped():
    raw = {
        "p1": {"adp_ppr": 3.0}, "p2": {}, "p3": {"adp_ppr": None},
        "p4": "not-a-dict", "p5": {"adp_ppr": "x"},
    }
    assert parse_adp(raw, field="adp_ppr") == {"p1": 3.0}


def test_parse_projected_points_keeps_zero_but_drops_missing():
    raw = {"p1": {"pts_ppr": 0.0}, "p2": {"pts_ppr": 210.4}, "p3": {}}
    assert parse_projected_points(raw, field="pts_ppr") == {"p1": 0.0, "p2": 210.4}


# --- deltas ---

def test_positive_delta_means_taken_later_than_the_market_had_him():
    assert adp_delta(pick_no=30, adp=12.0) == pytest.approx(18.0)


def test_negative_delta_means_reached():
    assert adp_delta(pick_no=5, adp=40.0) == pytest.approx(-35.0)


def test_delta_is_none_without_an_adp():
    assert adp_delta(pick_no=30, adp=None) is None


# --- per-owner rollup ---

def test_owner_grade_sums_matched_picks_and_reports_coverage():
    rows = [
        {"drafter_id": "u1", "adp_delta": 10.0},
        {"drafter_id": "u1", "adp_delta": -4.0},
        {"drafter_id": "u1", "adp_delta": None},
        {"drafter_id": "u2", "adp_delta": 2.0},
    ]
    out = owner_adp_grades(rows)
    assert out["u1"]["total_delta"] == pytest.approx(6.0)
    assert out["u1"]["graded_picks"] == 2
    assert out["u1"]["total_picks"] == 3
    assert out["u2"]["graded_picks"] == 1


def test_owner_with_no_matched_picks_reports_zero_coverage_not_a_score():
    """A team of kickers and defenses is not a zero-value draft; it is an
    ungraded one. Reporting 0.0 would read as average."""
    out = owner_adp_grades([{"drafter_id": "u1", "adp_delta": None}])
    assert out["u1"]["graded_picks"] == 0
    assert out["u1"]["total_delta"] is None


def test_keeper_rows_are_excluded_from_the_owner_grade():
    rows = [
        {"drafter_id": "u1", "adp_delta": 50.0, "is_keeper": True},
        {"drafter_id": "u1", "adp_delta": 5.0},
    ]
    out = owner_adp_grades(rows)
    assert out["u1"]["total_delta"] == pytest.approx(5.0)
    assert out["u1"]["graded_picks"] == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_draft_baselines.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sleeper_dynasty.engine.draft_baselines'`

- [ ] **Step 3: Write the implementation**

Create `src/sleeper_dynasty/engine/draft_baselines.py`:

```python
"""External expectation baselines for a draft: ADP and projected points.

Grading a pick is always *result minus expectation*. This module owns the two
expectations that come from outside the league — where the market drafted a
player, and how many points he was projected for — leaving the league-native
peer baseline to ``draft_signals.draft_skill``.

Both come from Sleeper's season projections payload
(``SleeperClient.get_projections``), which is keyed by native Sleeper
``player_id``, so nothing here needs an id crosswalk.

Pure. No I/O — callers thread in the fetched payload.
"""

from __future__ import annotations

from collections import defaultdict

# Sleeper's "never drafted" marker. It is NOT a 999th-overall ADP: left
# unfiltered it becomes a catch-all bucket that grades every undrafted player
# as though the market agreed on him. Same failure mode as DynastyProcess's
# literal "NA" key.
ADP_UNDRAFTED = 999.0

# Reception scoring at or above these thresholds selects the format. Sleeper
# leagues use 1.0 (PPR), 0.5 (half), or 0.0 (standard); the thresholds sit
# between them so unusual values (0.75, 0.25) land on the nearer format.
_PPR_FLOOR = 0.75
_HALF_PPR_FLOOR = 0.25


def adp_field_for(*, rec_points: float, superflex: bool) -> str:
    """Which ``adp_*`` field matches this league's scoring.

    Superflex wins outright: a second startable QB moves quarterbacks so far up
    the board that reception scoring is a rounding error by comparison.
    """
    if superflex:
        return "adp_2qb"
    if rec_points >= _PPR_FLOOR:
        return "adp_ppr"
    if rec_points >= _HALF_PPR_FLOOR:
        return "adp_half_ppr"
    return "adp_std"


def points_field_for(*, rec_points: float) -> str:
    """Which ``pts_*`` field matches this league's scoring.

    Sleeper publishes no superflex projection variant — projected points do not
    depend on roster construction the way draft position does.
    """
    if rec_points >= _PPR_FLOOR:
        return "pts_ppr"
    if rec_points >= _HALF_PPR_FLOOR:
        return "pts_half_ppr"
    return "pts_std"


def _numeric(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def parse_adp(raw: dict, *, field: str) -> dict[str, float]:
    """player_id -> ADP, sentinel and non-numeric entries dropped."""
    out: dict[str, float] = {}
    for pid, stats in (raw or {}).items():
        if not isinstance(stats, dict):
            continue
        val = _numeric(stats.get(field))
        if val is None or val >= ADP_UNDRAFTED:
            continue
        out[str(pid)] = val
    return out


def parse_projected_points(raw: dict, *, field: str) -> dict[str, float]:
    """player_id -> projected season points. Zero is kept (a real projection);
    missing is dropped (no projection published)."""
    out: dict[str, float] = {}
    for pid, stats in (raw or {}).items():
        if not isinstance(stats, dict):
            continue
        val = _numeric(stats.get(field))
        if val is None:
            continue
        out[str(pid)] = val
    return out


def adp_delta(*, pick_no: int, adp: float | None) -> float | None:
    """How far past his market price a player was taken.

    Positive = taken later than the market had him (value). Negative = a reach.
    None when the player has no ADP — the pick is ungraded on this baseline,
    which is not the same as scoring zero.
    """
    if adp is None:
        return None
    return float(pick_no) - float(adp)


def owner_adp_grades(rows: list[dict]) -> dict[str, dict]:
    """Roll per-pick ADP deltas up per owner, carrying coverage.

    ``total_delta`` is None for an owner with no matched picks. Reporting 0.0
    there would read as a league-average draft rather than an ungraded one.
    Keeper rows are excluded, matching ``draft_skill``.
    """
    totals: dict[str, float] = defaultdict(float)
    graded: dict[str, int] = defaultdict(int)
    seen: dict[str, int] = defaultdict(int)

    for r in rows:
        if r.get("is_keeper"):
            continue
        uid = str(r.get("drafter_id") or "")
        if not uid:
            continue
        seen[uid] += 1
        delta = r.get("adp_delta")
        if delta is None:
            continue
        totals[uid] += float(delta)
        graded[uid] += 1

    return {
        uid: {
            "total_delta": totals[uid] if graded[uid] else None,
            "graded_picks": graded[uid],
            "total_picks": seen[uid],
        }
        for uid in seen
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_draft_baselines.py -v`
Expected: PASS (13 tests)

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/draft_baselines.py tests/test_draft_baselines.py
git commit -m "feat(engine): ADP and projected-points baselines"
```

---

### Task 4: `build_draft_review` renders results before grades exist

**Files:**
- Modify: `src/sleeper_dynasty/engine/draft_results.py:166-228`
- Modify: `tests/test_draft_results.py` (create if absent)

**Interfaces:**
- Consumes: per-pick dicts carrying `draft_season`, `round`, `slot`, `picks_in_round`, `production_total`, `pick_no`.
- Produces: `build_draft_review(picks: list[dict]) -> dict | None` returning `{"season": int, "graded": bool, "best": dict | None, "worst": dict | None, "beat_slot": int, "total": int}`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_draft_results.py` (create the file with this import header if it does not exist):

```python
from sleeper_dynasty.engine.draft_results import build_draft_review


def _pick(pid, uid, rnd, slot, prod, *, season=2026, teams=12):
    return {
        "player_id": pid, "full_name": pid.upper(), "position": "RB",
        "drafter_id": uid, "round": rnd, "slot": slot, "picks_in_round": teams,
        "draft_season": season, "production_total": prod,
    }


def test_a_class_with_no_production_returns_results_not_none():
    """Draft night: every pick sits at 0.0. The board must still render who
    took whom — refusing to show a hollow grade is right, refusing to show the
    results is just an empty screen."""
    picks = [_pick("p1", "u1", 1, 1, 0.0), _pick("p2", "u2", 1, 2, 0.0)]
    review = build_draft_review(picks)
    assert review is not None
    assert review["graded"] is False
    assert review["best"] is None
    assert review["worst"] is None
    assert review["total"] == 2
    assert review["beat_slot"] == 0


def test_a_played_class_grades_normally():
    picks = [_pick("p1", "u1", 1, 1, 10.0), _pick("p2", "u2", 1, 2, 300.0)]
    review = build_draft_review(picks)
    assert review["graded"] is True
    assert review["best"]["player_id"] == "p2"
    assert review["best"]["slot_delta"] == 1
    assert review["worst"]["player_id"] == "p1"


def test_only_the_latest_season_is_reviewed():
    picks = [
        _pick("old", "u1", 1, 1, 500.0, season=2025),
        _pick("a", "u1", 1, 1, 10.0), _pick("b", "u2", 1, 2, 20.0),
    ]
    review = build_draft_review(picks)
    assert review["season"] == 2026
    assert review["total"] == 2


def test_fewer_than_two_picks_is_unreviewable():
    assert build_draft_review([_pick("p1", "u1", 1, 1, 50.0)]) is None
    assert build_draft_review([]) is None


def test_overall_position_spans_rounds():
    picks = [_pick("p1", "u1", 2, 1, 300.0), _pick("p2", "u2", 1, 1, 10.0)]
    review = build_draft_review(picks)
    # Round 2 slot 1 is the 13th pick; ranking 1st beats that slot by 12.
    assert review["best"]["draft_position"] == 13
    assert review["best"]["slot_delta"] == 12
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_draft_results.py -v`
Expected: FAIL — `TypeError: 'NoneType' object is not subscriptable` on the first test (current code returns `None` for a zero-production class).

- [ ] **Step 3: Write the implementation**

In `src/sleeper_dynasty/engine/draft_results.py`, replace `build_draft_review` entirely:

```python
def build_draft_review(picks: list[dict]) -> dict | None:
    """How the most recent draft panned out. Pure; None when unreviewable.

    Grades each pick by **rank against its own draft** rather than an external
    baseline: sort the class by production, and compare where a player finished
    to where he was taken. A back taken 13th who produced 1st beat his slot by
    12. That needs no ADP table, no positional model, and no assumption about
    what a given slot "should" return — the draft is its own yardstick, which
    is the only honest one when league size and scoring both vary.

    **Results and grades have different availability dates.** A class that has
    not played yet returns ``graded: False`` with null best/worst rather than
    None: right after a draft every pick sits at 0.0 and naming a "best pick"
    out of ties would invent one, but the results — who took whom, where — are
    real the moment the draft completes and must still render.

    None is reserved for a class that cannot be reviewed at all: no picks, or
    fewer than two.
    """
    if not picks:
        return None
    season = max(int(p.get("draft_season") or 0) for p in picks)
    field = [p for p in picks if int(p.get("draft_season") or 0) == season]
    if len(field) < 2:
        return None

    def position(p: dict) -> int:
        """Overall pick number. Round 2 slot 1 is the 13th pick, not the 1st."""
        explicit = int(p.get("pick_no") or 0)
        if explicit:
            return explicit
        per_round = int(p.get("picks_in_round") or 0)
        return (int(p.get("round") or 1) - 1) * per_round + int(p.get("slot") or 0)

    if not any(float(p.get("production_total") or 0.0) > 0 for p in field):
        return {
            "season": season, "graded": False,
            "best": None, "worst": None,
            "beat_slot": 0, "total": len(field),
        }

    # Rank by production, best first. The secondary key on draft position keeps
    # tied production deterministic instead of dependent on input order.
    ranked = sorted(
        field,
        key=lambda p: (-float(p.get("production_total") or 0.0), position(p)),
    )

    rows = []
    for rank, p in enumerate(ranked, start=1):
        pos = position(p)
        rows.append({
            "player_id": p.get("player_id"),
            "full_name": p.get("full_name") or p.get("player_id"),
            "position": p.get("position") or "",
            "drafter_id": p.get("drafter_id"),
            "round": int(p.get("round") or 0),
            "slot": int(p.get("slot") or 0),
            "draft_position": pos,
            "production_total": round(float(p.get("production_total") or 0.0), 1),
            # Positive = finished ahead of where he was taken.
            "slot_delta": pos - rank,
        })

    # Ties broken by production so the "best" of several equal deltas is the
    # one who actually scored more; the reverse for "worst".
    best = max(rows, key=lambda r: (r["slot_delta"], r["production_total"]))
    worst = min(rows, key=lambda r: (r["slot_delta"], r["production_total"]))
    return {
        "season": season,
        "graded": True,
        "best": best,
        "worst": worst,
        "beat_slot": sum(1 for r in rows if r["slot_delta"] > 0),
        "total": len(rows),
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_draft_results.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Update the API model to match**

In `api/app/models/league.py`, replace the `DraftReview` class:

```python
class DraftReview(BaseModel):
    """How the most recent draft panned out
    (engine/draft_results.py::build_draft_review).

    Drives the draft-window lead. Each pick is ranked against its own class
    rather than an external baseline, so no ADP table or positional model is
    needed.

    ``graded`` is False for a class that has not played yet — the results are
    real the moment the draft completes, but a "best pick" chosen out of an
    all-zero field would be invented. Consumers render results and omit the
    grade rather than falling back.
    """

    season: int
    graded: bool = True
    best: DraftReviewPick | None = None
    worst: DraftReviewPick | None = None
    beat_slot: int
    total: int
```

- [ ] **Step 6: Update the aggregation to pass it through**

In `api/app/services/aggregations.py`, inside `_draft_review`, replace the final `try` block:

```python
    try:
        graded = bool(raw.get("graded", True))
        return DraftReview(
            season=int(raw["season"]),
            graded=graded,
            best=_pick(raw["best"]) if graded and raw.get("best") else None,
            worst=_pick(raw["worst"]) if graded and raw.get("worst") else None,
            beat_slot=int(raw["beat_slot"]),
            total=int(raw["total"]),
        )
    except Exception:
        log.exception("draft review skipped for league %s", entry.league_id)
        return None
```

- [ ] **Step 7: Run the full backend suite**

Run: `pytest tests/ -q && pytest api/tests -q`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add src/sleeper_dynasty/engine/draft_results.py tests/test_draft_results.py \
        api/app/models/league.py api/app/services/aggregations.py
git commit -m "feat(engine): draft review renders results before grades exist"
```

---

## Phase 2 — Data plumbing

### Task 5: Draft-day ADP snapshot store

**Files:**
- Create: `api/app/services/adp_snapshot_store.py`
- Create: `api/tests/test_adp_snapshot_store.py`

**Interfaces:**
- Consumes: `parse_adp` output shape (`dict[str, float]`).
- Produces: `AdpSnapshotStore(cache_dir: Path)` with `capture(draft_id: str, adp_by_player: dict[str, float]) -> bool` and `read(draft_id: str) -> dict[str, float] | None`.

- [ ] **Step 1: Write the failing tests**

Create `api/tests/test_adp_snapshot_store.py`:

```python
from app.services.adp_snapshot_store import AdpSnapshotStore


def test_capture_then_read_round_trips(tmp_path):
    store = AdpSnapshotStore(tmp_path)
    assert store.capture("d1", {"p1": 12.5, "p2": 40.0}) is True
    assert store.read("d1") == {"p1": 12.5, "p2": 40.0}


def test_capture_is_write_once(tmp_path):
    """The draft-day baseline is the whole point. A later refresh must never
    overwrite it with mid-season ADP, or 'beat the market' becomes 'beat
    hindsight'."""
    store = AdpSnapshotStore(tmp_path)
    store.capture("d1", {"p1": 12.5})
    assert store.capture("d1", {"p1": 99.0}) is False
    assert store.read("d1") == {"p1": 12.5}


def test_read_of_an_uncaptured_draft_is_none(tmp_path):
    assert AdpSnapshotStore(tmp_path).read("nope") is None


def test_empty_capture_is_refused(tmp_path):
    """An empty ADP map means the fetch failed. Writing it would permanently
    poison this draft's baseline, since capture is write-once."""
    store = AdpSnapshotStore(tmp_path)
    assert store.capture("d1", {}) is False
    assert store.read("d1") is None


def test_corrupt_snapshot_reads_as_none(tmp_path):
    store = AdpSnapshotStore(tmp_path)
    store.capture("d1", {"p1": 1.0})
    (tmp_path / "adp" / "d1.json").write_text("{not json")
    assert store.read("d1") is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest api/tests/test_adp_snapshot_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.adp_snapshot_store'`

- [ ] **Step 3: Write the implementation**

Create `api/app/services/adp_snapshot_store.py`:

```python
"""Write-once draft-day ADP capture, keyed by draft_id.

Sleeper's ADP is *current* ADP and moves all preseason. Grading a draft in
December against December's ADP turns "did you beat the market" into "did you
beat hindsight" — which is production ranking again, with extra steps.

So the baseline is captured once, when the draft completes, and never
rewritten. Keying by draft_id rather than by date makes that immutability
structural: there is exactly one draft-day file per draft, and a second
capture is a no-op rather than a race.

Consequence: ADP grading works going forward only. A draft that completed
before this shipped has no snapshot and grades on the peer baseline alone.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

_SUBDIR = "adp"


class AdpSnapshotStore:
    def __init__(self, cache_dir: Path):
        self._dir = Path(cache_dir) / _SUBDIR

    def _path(self, draft_id: str) -> Path:
        return self._dir / f"{draft_id}.json"

    def capture(self, draft_id: str, adp_by_player: dict[str, float]) -> bool:
        """Record this draft's draft-day ADP. Returns whether a write happened.

        Refuses an empty map: an empty result means the fetch failed, and since
        capture is write-once, storing it would poison the baseline forever.
        """
        if not adp_by_player:
            log.warning(
                "refusing empty ADP capture for draft %s; fetch likely failed",
                draft_id)
            return False
        path = self._path(draft_id)
        if path.exists():
            return False
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(adp_by_player))
        except OSError:
            log.exception("ADP snapshot write failed for draft %s", draft_id)
            return False
        log.info(
            "captured draft-day ADP for draft %s (%d players)",
            draft_id, len(adp_by_player))
        return True

    def read(self, draft_id: str) -> dict[str, float] | None:
        """This draft's draft-day ADP, or None if never captured/unreadable.

        The try must span the coercion as well as the parse. A snapshot can be
        syntactically valid JSON and still be semantically corrupt — a value
        that is a non-numeric string raises ValueError, and one that is neither
        numeric nor string (a list, say) raises TypeError. Both must read as
        None: this store sits in a refresh path that degrades rather than
        fails. Mirrors KtcSnapshotStore._load, which wraps parse-and-construct
        in one try for exactly this reason.
        """
        path = self._path(draft_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            if not isinstance(data, dict):
                return None
            return {str(k): float(v) for k, v in data.items()}
        except (OSError, ValueError, TypeError):
            log.exception("ADP snapshot unreadable for draft %s", draft_id)
            return None
```

Add two tests to `api/tests/test_adp_snapshot_store.py` covering the semantic-corruption cases the syntactic test misses:

```python
def test_non_numeric_value_reads_as_none(tmp_path):
    """Valid JSON, invalid content. float("x") raises ValueError, which must
    not escape read()."""
    store = AdpSnapshotStore(tmp_path)
    store.capture("d1", {"p1": 1.0})
    (tmp_path / "adp" / "d1.json").write_text('{"p1": "not-a-number"}')
    assert store.read("d1") is None


def test_non_coercible_type_reads_as_none(tmp_path):
    """float([]) raises TypeError, not ValueError — the except tuple must
    cover both."""
    store = AdpSnapshotStore(tmp_path)
    store.capture("d1", {"p1": 1.0})
    (tmp_path / "adp" / "d1.json").write_text('{"p1": [1, 2]}')
    assert store.read("d1") is None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest api/tests/test_adp_snapshot_store.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add api/app/services/adp_snapshot_store.py api/tests/test_adp_snapshot_store.py
git commit -m "feat(api): write-once draft-day ADP snapshot store"
```

---

### Task 6: Wire `DraftClass`, ADP, and projections into the grader

**Files:**
- Modify: `api/app/services/grader.py:727-763` (draft inputs) and `:885-953` (drafted-pick results)
- Modify: `api/app/services/rating_signals.py:127-130`
- Modify: `src/sleeper_dynasty/engine/draft_results.py:100-163` (`build_drafted_pick_results`)
- Modify: `api/tests/test_grader_draft_inputs.py` (create)

**Interfaces:**
- Consumes: `build_draft_classes` / `build_draft_picks` (Task 1), `draft_skill(axis=…)` (Task 2), `parse_adp` / `parse_projected_points` / `adp_delta` (Task 3), `AdpSnapshotStore` (Task 5).
- Produces: `drafted_picks` rows gaining `pick_no: int`, `is_keeper: bool`, `draft_kind: str`, `adp: float | None`, `adp_delta: float | None`, `projected_points: float | None`. `ChainCacheEntry.drafted_picks` shape only — no new persisted field.

- [ ] **Step 1: Extend `build_drafted_pick_results`**

In `src/sleeper_dynasty/engine/draft_results.py`, add two parameters to the signature and the corresponding row fields:

```python
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
    games_fn: Callable[[str, str], int],
    current_holders: dict[str, str],
    traded_away_set: set[tuple[str, str]],
    adp_by_player: dict[str, float] | None = None,
    projected_by_player: dict[str, float] | None = None,
) -> list[dict]:
```

Inside the per-pick loop, after `lo, hi = min(lo, cur), max(hi, cur)`, add:

```python
        adp = (adp_by_player or {}).get(p.player_id)
        projected = (projected_by_player or {}).get(p.player_id)
```

and add these keys to the appended dict:

```python
            "pick_no": p.pick_no,
            "is_keeper": p.is_keeper,
            "draft_kind": p.draft_kind,
            "adp": adp,
            "adp_delta": adp_delta(pick_no=p.pick_no, adp=adp),
            "projected_points": projected,
```

Add the import at the top of the file:

```python
from sleeper_dynasty.engine.draft_baselines import adp_delta
```

- [ ] **Step 2: Write the failing grader test**

Create `api/tests/test_grader_draft_inputs.py`:

```python
import pytest

from sleeper_dynasty.engine.draft_class import build_draft_classes, build_draft_picks
from sleeper_dynasty.engine.draft_results import build_drafted_pick_results


def _drafts(player_type, season=2026):
    return {"lg": [{
        "draft_id": "d1", "league_id": "lg", "season": str(season),
        "status": "complete", "type": "snake",
        "settings": {"rounds": 2, "teams": 2, "player_type": player_type},
    }]}


def _picks():
    return {"d1": [
        {"round": 1, "draft_slot": 1, "pick_no": 1, "player_id": "p1",
         "picked_by": "u1", "is_keeper": None},
        {"round": 1, "draft_slot": 2, "pick_no": 2, "player_id": "p2",
         "picked_by": "u2", "is_keeper": True},
    ]}


def _rows(classes, adp=None, projected=None):
    picks = build_draft_picks(
        classes=classes, picks_by_draft_id=_picks(),
        roster_to_user_by_league={})
    return build_drafted_pick_results(
        picks,
        ktc_floats={}, normalized_name_by_pid={},
        names={"p1": "Player One", "p2": "Player Two"},
        positions={"p1": "RB", "p2": "WR"}, extremes_by_name={},
        acquired_set=set(), points_fn=lambda *_: 0.0, games_fn=lambda *_: 0,
        current_holders={}, traded_away_set=set(),
        adp_by_player=adp, projected_by_player=projected,
    )


def test_redraft_rows_carry_adp_delta_and_projection():
    classes = build_draft_classes(
        drafts_by_league=_drafts(0), league_format="redraft",
        origin_season=2026)
    rows = _rows(classes, adp={"p1": 12.0}, projected={"p1": 210.5})
    row = next(r for r in rows if r["player_id"] == "p1")
    assert row["adp"] == pytest.approx(12.0)
    assert row["adp_delta"] == pytest.approx(-11.0)  # taken 1st, market said 12
    assert row["projected_points"] == pytest.approx(210.5)
    assert row["draft_kind"] == "full"


def test_unmatched_player_has_null_adp_not_zero():
    classes = build_draft_classes(
        drafts_by_league=_drafts(0), league_format="redraft",
        origin_season=2026)
    rows = _rows(classes, adp={})
    assert all(r["adp"] is None and r["adp_delta"] is None for r in rows)


def test_keeper_flag_survives_into_the_rows():
    classes = build_draft_classes(
        drafts_by_league=_drafts(0), league_format="redraft",
        origin_season=2026)
    rows = _rows(classes)
    assert {r["player_id"]: r["is_keeper"] for r in rows} == {
        "p1": False, "p2": True}


def test_redraft_year_one_is_ingested():
    """The draft happening in the chain's origin season is the graded event in
    a redraft league, not a startup to discard."""
    classes = build_draft_classes(
        drafts_by_league=_drafts(0, season=2026), league_format="redraft",
        origin_season=2026)
    assert len(classes) == 1
    assert len(_rows(classes)) == 2
```

- [ ] **Step 3: Run to verify it fails**

Run: `pytest api/tests/test_grader_draft_inputs.py -v`
Expected: FAIL — `build_drafted_pick_results() got an unexpected keyword argument 'adp_by_player'` until Step 1 is applied; after Step 1, PASS.

- [ ] **Step 4: Rewrite the grader's draft-inputs block**

In `api/app/services/grader.py`, replace the block at lines 727–763 (`# Draft inputs for the Outlook signals…` through its `except`):

```python
        # Draft inputs (best-effort: empty -> signals 0).
        traded_picks: list = []
        rookie_picks: list = []
        draft_classes: list = []
        adp_by_player: dict[str, float] = {}
        projected_by_player: dict[str, float] = {}
        num_draft_rounds = 4
        current_league_drafts: list = []  # for the league-phase draft window
        try:
            from sleeper_dynasty.engine.draft_class import (
                build_draft_classes, build_draft_picks,
            )
            from app.services.grader_io import is_redraft_chain

            traded_picks = await client.get_traded_picks(current_league_id)
            origin_season = min(lg.season for lg in chain)
            latest = max(chain, key=lambda lg: lg.season)
            league_format = getattr(latest, "format", "dynasty") or "dynasty"

            drafts_by_league: dict[str, list] = {}
            picks_by_draft_id: dict[str, list] = {}
            for lg in chain:
                drafts = await client.get_drafts(lg.league_id)
                drafts_by_league[lg.league_id] = drafts
                if lg.league_id == current_league_id:
                    current_league_drafts = drafts

            draft_classes = build_draft_classes(
                drafts_by_league=drafts_by_league,
                league_format=league_format,
                origin_season=origin_season,
            )
            for cls in draft_classes:
                picks_by_draft_id[cls.draft_id] = \
                    await client.get_draft_picks(cls.draft_id)

            rookie_picks = build_draft_picks(
                classes=draft_classes,
                picks_by_draft_id=picks_by_draft_id,
                roster_to_user_by_league=supporting["roster_to_user_by_league"],
            )
            if draft_classes:
                newest = max(draft_classes, key=lambda c: c.season)
                for d in drafts_by_league.get(newest.league_id, []):
                    if d.get("draft_id") == newest.draft_id:
                        num_draft_rounds = int(
                            (d.get("settings") or {}).get("rounds", 4))
        except Exception:
            log.exception("draft inputs fetch failed; draft signals will be 0")

        # ADP + projected points (best-effort: absent -> those columns drop).
        try:
            from sleeper_dynasty.engine.draft_baselines import (
                adp_field_for, parse_adp, parse_projected_points,
                points_field_for,
            )
            from app.services.adp_snapshot_store import AdpSnapshotStore

            latest = max(chain, key=lambda lg: lg.season)
            scoring = getattr(latest, "scoring_settings", {}) or {}
            rec_points = float(scoring.get("rec") or 0.0)
            roster_positions = list(
                getattr(latest, "roster_positions", []) or [])
            superflex = (
                "SUPER_FLEX" in roster_positions
                or roster_positions.count("QB") > 1
            )

            # Projections change at most daily; a refresh runs far more often
            # than that. Cache through FileCache on the same day-keyed pattern
            # the injury map uses, so the scheduler does not re-pull a ~9,400
            # player payload every interval. FileCache.read defaults to a
            # one-day max age, so no explicit TTL is needed here.
            from sleeper_dynasty.cache import FileCache

            _fc = FileCache(cache_dir) if cache_dir is not None else None
            _proj_key = f"sleeper_projections_{latest.season}"
            raw_proj = _fc.read(_proj_key) if _fc is not None else None
            if not raw_proj:
                raw_proj = await client.get_projections(latest.season)
                if _fc is not None and raw_proj:
                    _fc.write(_proj_key, raw_proj)

            live_adp = parse_adp(
                raw_proj,
                field=adp_field_for(rec_points=rec_points, superflex=superflex))
            projected_by_player = parse_projected_points(
                raw_proj, field=points_field_for(rec_points=rec_points))

            # Capture the draft-day baseline for any completed class that does
            # not have one yet, then read every class's baseline back. Live ADP
            # is never used for grading — only for the capture.
            adp_store = (
                AdpSnapshotStore(cache_dir) if cache_dir is not None else None
            )
            if adp_store is not None:
                for cls in draft_classes:
                    if cls.season == latest.season:
                        adp_store.capture(cls.draft_id, live_adp)
                for cls in draft_classes:
                    snap = adp_store.read(cls.draft_id)
                    if snap:
                        adp_by_player.update(snap)
        except Exception:
            log.exception("ADP/projection fetch skipped; those columns drop")
```

- [ ] **Step 5: Pass the new inputs into `build_drafted_pick_results`**

In `api/app/services/grader.py`, in the `drafted_picks = build_drafted_pick_results(` call (~line 940), add two arguments before the closing paren:

```python
                adp_by_player=adp_by_player,
                projected_by_player=projected_by_player,
```

- [ ] **Step 6: Thread the axis into `draft_skill`**

In `api/app/services/rating_signals.py`, add `axis: str = "blend"` as a keyword-only parameter to `compute_rating_signals`, and pass it through at line ~127:

```python
    draft_skill_by_uid = draft_skill(
        picks=rookie_picks or [], ktc_by_player=ktc_floats,
        production_by_player=production_by_player,
        games_by_player=games_by_player, min_games=17, axis=axis)
```

and at the per-season call further down:

```python
            season_draft_skill[str(season)] = draft_skill(
                picks=s_picks,
                ktc_by_player=ktc_floats,
                production_by_player=production_by_player,
                games_by_player=games_by_player, min_games=17, axis=axis)
```

In `api/app/services/grader.py`, at the `compute_rating_signals(` call (~line 852), pass:

```python
                axis="production" if is_redraft_chain(chain) or (
                    getattr(max(chain, key=lambda lg: lg.season), "format", "")
                    == "keeper") else "blend",
```

- [ ] **Step 7: Run the full backend suite**

Run: `pytest tests/ -q && pytest api/tests -q`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add api/app/services/grader.py api/app/services/rating_signals.py \
        src/sleeper_dynasty/engine/draft_results.py \
        api/tests/test_grader_draft_inputs.py
git commit -m "feat(api): wire DraftClass, ADP, and projections into refresh"
```

---

### Task 6b: Daily dated ADP, resolved to each draft's own date

**Files:**
- Modify: `api/app/services/adp_snapshot_store.py`
- Modify: `api/app/services/grader.py` (the ADP block from Task 6)
- Modify: `api/tests/test_adp_snapshot_store.py`

**Interfaces:**
- Consumes: `parse_adp` output; Sleeper draft objects (which carry `last_picked`, epoch ms).
- Produces: `AdpSnapshotStore.capture_daily(adp_by_player: dict[str, float], today: date) -> bool`, `AdpSnapshotStore.list_dates() -> list[date]`, `AdpSnapshotStore.resolve_for_draft(draft_id: str, drafted_on: date) -> dict[str, float] | None`. `capture`/`read` keep their existing write-once per-draft contract.

**Why this task exists:** Task 6 captured whatever ADP was current on the refresh that first noticed a completed draft. That is wrong whenever the refresh does not coincide with the draft. Verified live: the dynasty league's rookie draft has `last_picked = 2026-05-06`, so a first refresh in August would have stamped August ADP onto a May draft. A league drafting Aug 1 and one drafting Aug 26 draft against genuinely different markets and must be graded against their own. ADP is league-specific because draft dates are.

**The recoverable/unrecoverable line:** daily snapshots only exist from the day capture begins. Drafts completed before that get no ADP baseline, permanently — there is no historical ADP endpoint. They grade on the peer baseline alone, unaffected.

- [ ] **Step 1: Write the failing tests**

Append to `api/tests/test_adp_snapshot_store.py`:

```python
from datetime import date


def test_daily_capture_is_dated_and_listable(tmp_path):
    store = AdpSnapshotStore(tmp_path)
    assert store.capture_daily({"p1": 3.0}, date(2026, 8, 14)) is True
    assert store.capture_daily({"p1": 5.0}, date(2026, 8, 16)) is True
    assert store.list_dates() == [date(2026, 8, 14), date(2026, 8, 16)]


def test_daily_capture_is_write_once_per_day(tmp_path):
    store = AdpSnapshotStore(tmp_path)
    store.capture_daily({"p1": 3.0}, date(2026, 8, 14))
    assert store.capture_daily({"p1": 99.0}, date(2026, 8, 14)) is False


def test_empty_daily_capture_is_refused(tmp_path):
    assert AdpSnapshotStore(tmp_path).capture_daily({}, date(2026, 8, 14)) is False


def test_resolve_uses_the_snapshot_from_the_drafts_own_day(tmp_path):
    """Two leagues, two draft dates, two different markets."""
    store = AdpSnapshotStore(tmp_path)
    store.capture_daily({"p1": 3.0}, date(2026, 8, 1))
    store.capture_daily({"p1": 20.0}, date(2026, 8, 26))
    assert store.resolve_for_draft("early", date(2026, 8, 1)) == {"p1": 3.0}
    assert store.resolve_for_draft("late", date(2026, 8, 26)) == {"p1": 20.0}


def test_resolve_falls_back_to_the_nearest_earlier_day(tmp_path):
    """A draft is graded against the market as it stood going IN, never after."""
    store = AdpSnapshotStore(tmp_path)
    store.capture_daily({"p1": 3.0}, date(2026, 8, 10))
    store.capture_daily({"p1": 20.0}, date(2026, 8, 20))
    assert store.resolve_for_draft("mid", date(2026, 8, 15)) == {"p1": 3.0}


def test_resolve_is_none_when_no_snapshot_predates_the_draft(tmp_path):
    """A draft older than our snapshot history has no baseline, permanently.
    Returning a later snapshot would be grading against hindsight."""
    store = AdpSnapshotStore(tmp_path)
    store.capture_daily({"p1": 3.0}, date(2026, 8, 20))
    assert store.resolve_for_draft("ancient", date(2026, 5, 6)) is None


def test_resolve_pins_the_result_write_once(tmp_path):
    """Once resolved, a draft's baseline is frozen — later daily snapshots
    must never change it."""
    store = AdpSnapshotStore(tmp_path)
    store.capture_daily({"p1": 3.0}, date(2026, 8, 1))
    assert store.resolve_for_draft("d1", date(2026, 8, 1)) == {"p1": 3.0}
    store.capture_daily({"p1": 99.0}, date(2026, 8, 2))
    assert store.resolve_for_draft("d1", date(2026, 8, 2)) == {"p1": 3.0}
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest api/tests/test_adp_snapshot_store.py -v`
Expected: FAIL — `AttributeError: 'AdpSnapshotStore' object has no attribute 'capture_daily'`

- [ ] **Step 3: Extend the store**

Add to `api/app/services/adp_snapshot_store.py` (keep `capture`/`read` exactly as they are — `resolve_for_draft` builds on them):

```python
_DAILY_SUBDIR = "daily"


    def _daily_path(self, d: date) -> Path:
        return self._dir / _DAILY_SUBDIR / f"{d.isoformat()}.json"

    def capture_daily(self, adp_by_player: dict[str, float], today: date) -> bool:
        """Write today's ADP if absent and non-empty. Returns True if written.

        Captured unconditionally on refresh, not only when a draft completes:
        we cannot know in advance which day a league will draft, and ADP as of
        that day is unrecoverable afterwards.
        """
        if not adp_by_player:
            log.warning("refusing empty daily ADP capture for %s", today)
            return False
        path = self._daily_path(today)
        if path.exists():
            return False
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(adp_by_player))
        except OSError:
            log.exception("daily ADP snapshot write failed for %s", today)
            return False
        return True

    def list_dates(self) -> list[date]:
        """Every daily-snapshot date we hold, ascending."""
        out: list[date] = []
        for p in (self._dir / _DAILY_SUBDIR).glob("*.json"):
            try:
                out.append(date.fromisoformat(p.stem))
            except ValueError:
                continue
        return sorted(out)

    def resolve_for_draft(
        self, draft_id: str, drafted_on: date
    ) -> dict[str, float] | None:
        """This draft's frozen baseline, resolving it from daily history once.

        Resolution picks the snapshot dated on the draft's own day, else the
        nearest EARLIER day — a draft is graded against the market as it stood
        going in, never after. Returns None when no snapshot predates the
        draft: that draft is older than our history and has no baseline,
        permanently. Handing back a later snapshot would be exactly the
        hindsight grading this store exists to prevent.

        The resolved result is pinned via the write-once per-draft file, so
        later daily captures can never move a baseline that already exists.
        """
        pinned = self.read(draft_id)
        if pinned is not None:
            return pinned
        candidates = [d for d in self.list_dates() if d <= drafted_on]
        if not candidates:
            return None
        snap = self._load_daily(max(candidates))
        if not snap:
            return None
        self.capture(draft_id, snap)
        return snap

    def _load_daily(self, d: date) -> dict[str, float] | None:
        path = self._daily_path(d)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            if not isinstance(data, dict):
                return None
            return {str(k): float(v) for k, v in data.items()}
        except (OSError, ValueError, TypeError):
            log.exception("daily ADP snapshot unreadable for %s", d)
            return None
```

Add `from datetime import date` to the module imports.

- [ ] **Step 4: Run to verify they pass**

Run: `pytest api/tests/test_adp_snapshot_store.py -v`
Expected: PASS (14 tests — 7 from Task 5, 7 new)

- [ ] **Step 5: Rewire the grader's ADP block**

In `api/app/services/grader.py`, replace the capture/read loops from Task 6. Daily capture runs unconditionally; per-draft resolution keys off each draft's own `last_picked`:

**Two things to get right, both of which bit the first implementation:**

- Do **not** write `from datetime import date, timezone` inside `run()`. Binding `timezone` locally shadows the module-level import for the *entire method*, so an earlier pre-existing use of `timezone.utc` raises `UnboundLocalError`. Use `import datetime as _dt` (a distinct name) and let `timezone` resolve to the module-level import.
- Pre-initialize `drafts_by_league: dict[str, list] = {}` alongside the other outputs at the top of the draft-inputs block, **before** its `try`. It is otherwise first assigned inside that try, so a failure before that line (a raising `get_traded_picks`, an empty chain) leaves it unbound and the loop below raises instead of no-op'ing.

```python
            import datetime as _dt

            adp_store = (
                AdpSnapshotStore(cache_dir) if cache_dir is not None else None
            )
            if adp_store is not None:
                # Unconditional: we cannot know which day a league will draft,
                # and that day's ADP is unrecoverable afterwards.
                adp_store.capture_daily(live_adp, _dt.datetime.now(timezone.utc).date())

                # Each draft resolves against ITS OWN day's market. A league
                # drafting Aug 1 and one drafting Aug 26 are grading against
                # genuinely different boards.
                last_picked_by_draft: dict[str, int] = {}
                for _lg_id, _drafts in drafts_by_league.items():
                    for _d in _drafts:
                        lp = _d.get("last_picked") or _d.get("start_time")
                        if lp:
                            last_picked_by_draft[str(_d.get("draft_id"))] = int(lp)

                for cls in draft_classes:
                    lp_ms = last_picked_by_draft.get(cls.draft_id)
                    if not lp_ms:
                        continue
                    drafted_on = _dt.datetime.fromtimestamp(
                        lp_ms / 1000, tz=timezone.utc).date()
                    snap = adp_store.resolve_for_draft(cls.draft_id, drafted_on)
                    if snap:
                        adp_by_draft[cls.draft_id] = snap
```

`drafts_by_league` is populated in the draft-inputs block above. With the pre-initialization noted earlier it is `{}` on any failure and this loop is a clean no-op — which is the correct degradation. Without it, an early failure leaves the name unbound and the loop raises, which the outer `except` then catches and mislabels as a skipped fetch.

- [ ] **Step 6: Run both suites**

Run: `pytest tests/ -q && pytest api/tests -q`
Expected: PASS. The API suite takes ~2.5 minutes.

- [ ] **Step 7: Commit**

```bash
git add api/app/services/adp_snapshot_store.py api/app/services/grader.py \
        api/tests/test_adp_snapshot_store.py
git commit -m "fix(api): resolve each draft's ADP baseline to its own draft date"
```

---

## Phase 3 — API surface

### Task 7: Draft board endpoint

**Files:**
- Create: `api/app/services/draft_board_view.py`
- Create: `api/app/routes/draft.py`
- Create: `api/tests/test_draft_board_view.py`
- Modify: `api/app/models/league.py` (add `DraftBoardPick`, `DraftBoardOwner`, `DraftBoardResp`)
- Modify: `api/app/main.py` (register the router)

**Interfaces:**
- Consumes: `ChainCacheEntry.drafted_picks` rows carrying `pick_no`, `is_keeper`, `adp`, `adp_delta`, `projected_points` (Task 6); `owner_adp_grades` (Task 3).
- Produces: `GET /api/league/{league_id}/draft/{season}` → `DraftBoardResp` with `season: int`, `seasons: list[int]`, `graded: bool`, `format: str`, `picks: list[DraftBoardPick]`, `owners: list[DraftBoardOwner]`.

- [ ] **Step 1: Write the failing tests**

Create `api/tests/test_draft_board_view.py`:

```python
import pytest

from app.services.draft_board_view import build_draft_board


class _Entry:
    league_id = "lg"
    owners = {"u1": {"display_name": "Alice"}, "u2": {"display_name": "Bob"}}
    capabilities = {"format": "redraft"}

    def __init__(self, picks):
        self.drafted_picks = picks


def _pick(pid, uid, pick_no, season=2026, **kw):
    row = {
        "player_id": pid, "full_name": pid.upper(), "position": "RB",
        "drafter_id": uid, "round": 1, "slot": pick_no,
        "picks_in_round": 2, "draft_season": season, "pick_no": pick_no,
        "is_keeper": False, "draft_kind": "full",
        "production_total": 0.0, "adp": None, "adp_delta": None,
        "projected_points": None,
    }
    row.update(kw)
    return row


def test_board_lists_picks_in_draft_order():
    entry = _Entry([_pick("p2", "u2", 2), _pick("p1", "u1", 1)])
    board = build_draft_board(entry, season=2026)
    assert [p.player_id for p in board.picks] == ["p1", "p2"]


def test_board_is_ungraded_before_any_production():
    entry = _Entry([_pick("p1", "u1", 1), _pick("p2", "u2", 2)])
    assert build_draft_board(entry, season=2026).graded is False


def test_board_is_graded_once_production_exists():
    entry = _Entry([
        _pick("p1", "u1", 1, production_total=100.0),
        _pick("p2", "u2", 2),
    ])
    assert build_draft_board(entry, season=2026).graded is True


def test_owner_rows_carry_adp_total_and_coverage():
    entry = _Entry([
        _pick("p1", "u1", 1, adp=12.0, adp_delta=-11.0),
        _pick("p2", "u1", 3, adp=None, adp_delta=None),
    ])
    board = build_draft_board(entry, season=2026)
    row = next(o for o in board.owners if o.user_id == "u1")
    assert row.adp_total_delta == pytest.approx(-11.0)
    assert row.graded_picks == 1
    assert row.total_picks == 2


def test_seasons_lists_every_available_class_newest_first():
    entry = _Entry([
        _pick("p1", "u1", 1, season=2025), _pick("p2", "u2", 2, season=2025),
        _pick("p3", "u1", 1, season=2026), _pick("p4", "u2", 2, season=2026),
    ])
    assert build_draft_board(entry, season=2026).seasons == [2026, 2025]


def test_unknown_season_returns_none():
    assert build_draft_board(_Entry([_pick("p1", "u1", 1)]), season=1999) is None


def test_empty_picks_returns_none():
    assert build_draft_board(_Entry([]), season=2026) is None


def test_keeper_picks_appear_on_the_board_but_not_in_the_owner_grade():
    entry = _Entry([
        _pick("p1", "u1", 1, is_keeper=True, adp=1.0, adp_delta=0.0),
        _pick("p2", "u1", 2, adp=20.0, adp_delta=-18.0),
    ])
    board = build_draft_board(entry, season=2026)
    assert len(board.picks) == 2
    assert any(p.is_keeper for p in board.picks)
    row = next(o for o in board.owners if o.user_id == "u1")
    assert row.graded_picks == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest api/tests/test_draft_board_view.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.draft_board_view'`

- [ ] **Step 3: Add the response models**

Append to `api/app/models/league.py`:

```python
class DraftBoardPick(BaseModel):
    """One pick on the league-wide draft board."""

    player_id: str
    full_name: str
    position: str
    drafter_id: str
    owner: OwnerRef | None = None
    round: int
    slot: int
    pick_no: int
    is_keeper: bool = False
    production_total: float = 0.0
    # Null rather than zero when the player has no market/projection reading.
    adp: float | None = None
    adp_delta: float | None = None
    projected_points: float | None = None


class DraftBoardOwner(BaseModel):
    """One owner's summary for a single draft class.

    ``adp_total_delta`` is null for an owner with no matched picks — an
    ungraded draft, not an average one. ``graded_picks`` / ``total_picks``
    state the coverage so the reader knows what the number covers.
    """

    user_id: str
    owner: OwnerRef | None = None
    adp_total_delta: float | None = None
    graded_picks: int = 0
    total_picks: int = 0
    production_total: float = 0.0


class DraftBoardResp(BaseModel):
    league_id: str
    season: int
    seasons: list[int]
    # False until the class has played. Consumers render results and omit the
    # grade columns rather than showing zeros.
    graded: bool
    format: str = "dynasty"
    picks: list[DraftBoardPick]
    owners: list[DraftBoardOwner]
```

- [ ] **Step 4: Write the view builder**

Create `api/app/services/draft_board_view.py`:

```python
"""Assemble the league-wide draft board for one season.

The board is the only screen that shows a whole draft class at once. It has to
work on draft night — when every pick sits at 0.0 production — so results and
grades are separated: picks always render, grade columns appear only once the
class has played.
"""

from __future__ import annotations

import logging

from app.models.league import DraftBoardOwner, DraftBoardPick, DraftBoardResp
from app.services.aggregations import owner_ref
from sleeper_dynasty.engine.draft_baselines import owner_adp_grades

log = logging.getLogger(__name__)


def available_seasons(entry) -> list[int]:
    """Every draft season on this chain, newest first."""
    return sorted(
        {int(p.get("draft_season") or 0)
         for p in (getattr(entry, "drafted_picks", None) or [])
         if p.get("draft_season")},
        reverse=True,
    )


def build_draft_board(entry, *, season: int) -> DraftBoardResp | None:
    """One season's board, or None when there is nothing to show."""
    rows = [
        p for p in (getattr(entry, "drafted_picks", None) or [])
        if int(p.get("draft_season") or 0) == int(season)
    ]
    if not rows:
        return None

    rows = sorted(rows, key=lambda r: (
        int(r.get("pick_no") or 0) or
        (int(r.get("round") or 1) - 1) * int(r.get("picks_in_round") or 0)
        + int(r.get("slot") or 0)
    ))

    graded = any(float(r.get("production_total") or 0.0) > 0 for r in rows)

    picks = [
        DraftBoardPick(
            player_id=str(r.get("player_id") or ""),
            full_name=str(r.get("full_name") or r.get("player_id") or ""),
            position=str(r.get("position") or ""),
            drafter_id=str(r.get("drafter_id") or ""),
            owner=owner_ref(entry, str(r.get("drafter_id") or "")) or None,
            round=int(r.get("round") or 0),
            slot=int(r.get("slot") or 0),
            pick_no=int(r.get("pick_no") or 0),
            is_keeper=bool(r.get("is_keeper")),
            production_total=float(r.get("production_total") or 0.0),
            adp=r.get("adp"),
            adp_delta=r.get("adp_delta"),
            projected_points=r.get("projected_points"),
        )
        for r in rows
    ]

    grades = owner_adp_grades(rows)
    production_by_owner: dict[str, float] = {}
    for r in rows:
        uid = str(r.get("drafter_id") or "")
        production_by_owner[uid] = production_by_owner.get(uid, 0.0) + float(
            r.get("production_total") or 0.0)

    owners = [
        DraftBoardOwner(
            user_id=uid,
            owner=owner_ref(entry, uid) or None,
            adp_total_delta=g["total_delta"],
            graded_picks=g["graded_picks"],
            total_picks=g["total_picks"],
            production_total=production_by_owner.get(uid, 0.0),
        )
        for uid, g in grades.items()
    ]
    # Best draft first when graded; alphabetical-stable otherwise.
    owners.sort(
        key=lambda o: (
            o.production_total if graded
            else (o.adp_total_delta if o.adp_total_delta is not None else 0.0)
        ),
        reverse=True,
    )

    fmt = str((getattr(entry, "capabilities", None) or {}).get("format")
              or "dynasty")

    return DraftBoardResp(
        league_id=entry.league_id,
        season=int(season),
        seasons=available_seasons(entry),
        graded=graded,
        format=fmt,
        picks=picks,
        owners=owners,
    )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest api/tests/test_draft_board_view.py -v`
Expected: PASS (8 tests)

- [ ] **Step 6: Add the route**

Create `api/app/routes/draft.py`. This mirrors `api/app/routes/league.py` exactly — routes declare the **full** `/api/...` path (there is no router prefix in this codebase), `_cache_dir()` is the patch point tests use, and a cold cache is a 409 with the standard detail string:

```python
"""League-wide draft board."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.deps import get_cache_dir
from app.models.league import DraftBoardResp
from app.services.chain_cache import ChainCache
from app.services.draft_board_view import available_seasons, build_draft_board
from app.services.identity import apply_name_overrides
from app.services.name_override_store import NameOverrideStore

log = logging.getLogger(__name__)
router = APIRouter()


def _cache_dir() -> Path:
    """Indirection point; tests patch this to point at tmp_path."""
    return get_cache_dir()


@router.get("/api/league/{league_id}/draft/{season}",
            response_model=DraftBoardResp)
def draft_board(league_id: str, season: int) -> DraftBoardResp:
    """One draft class, every owner.

    409 on a cold cache, matching every other dashboard endpoint. 404 names the
    seasons that *do* exist, so a wrong-year link is self-correcting.
    """
    cache_dir = _cache_dir()
    cache = ChainCache(cache_dir=cache_dir)
    entry = cache.read(league_id)
    if entry is None:
        raise HTTPException(
            status_code=409,
            detail="cache cold: kick off refresh via POST /api/league/{id}/refresh",
        )
    overrides = NameOverrideStore(cache_dir=cache_dir).read(league_id)
    if overrides:
        apply_name_overrides(entry, overrides)

    board = build_draft_board(entry, season=season)
    if board is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"no draft class for season {season}; "
                f"available: {available_seasons(entry) or 'none'}"
            ),
        )
    return board
```

- [ ] **Step 7: Register the router**

In `api/app/main.py`, alongside the other league-gated routers (~line 90):

```python
    app.include_router(draft.router, dependencies=league_guard)
```

and add `draft` to the `from app.routes import (...)` block at the top. **Do not pass a `prefix`** — every router in this app declares full `/api/...` paths itself.

- [ ] **Step 8: Run the backend suite**

Run: `pytest api/tests -q`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add api/app/services/draft_board_view.py api/app/routes/draft.py \
        api/app/models/league.py api/app/main.py \
        api/tests/test_draft_board_view.py
git commit -m "feat(api): league-wide draft board endpoint"
```

---

## Phase 4 — UI

### Task 8: Draft tab escapes the Outlook gate

**Files:**
- Modify: `web/components/OwnerDeepDive.tsx:53-58, 232-238`
- Modify: `web/components/ownerdeepdive/FutureDraftTab.tsx:153`
- Modify: `web/components/ownerdeepdive/PastPicksTable.tsx`
- Modify: `web/lib/types.ts`
- Create: `web/tests/draft-tab.test.tsx`

**Interfaces:**
- Consumes: `OwnerDetailResp.draft_picks_by_season` (already shipped).
- Produces: a `"draft"` `TabKey`; `DraftPickResult` gains `is_keeper?: boolean`, `pick_no?: number`, `adp?: number | null`, `adp_delta?: number | null`, `projected_points?: number | null`.

**Why this task exists:** `PastPicksTable` renders inside `FutureDraftTab`, and the Outlook tab is dropped wholesale for redraft leagues. The per-pick data ships in the response today and no screen shows it. Gating the tab on the picks themselves is the fix.

- [ ] **Step 1: Invoke the styling skill**

Run the `agate-styling` skill and follow it for every change in this task. New columns use `.ruled` rows, Geist Mono figures, and color only on signed numbers.

- [ ] **Step 2: Write the failing test**

Create `web/tests/draft-tab.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { OwnerDeepDive } from "@/components/OwnerDeepDive";

function detail(overrides: Record<string, unknown> = {}) {
  return {
    league_id: "lg", user_id: "u1",
    owner: { user_id: "u1", owner_name: "Alice" },
    totals_by_lens: {}, career_arc: [], trades: [],
    draft_picks_by_season: {
      "2026": [{
        player_id: "p1", full_name: "Player One", position: "RB",
        round: 1, slot: 1, picks_in_round: 12, draft_season: 2026,
        acquired_via_trade: false, current_value: 0, lowest_value: 0,
        highest_value: 0, avg_slot_value: 0, production_total: 0,
        production_regular: 0, production_playoff: 0, production_toilet: 0,
        games_started: 0, roster_status: "rostered",
      }],
    },
    ...overrides,
  } as never;
}

describe("owner Draft tab", () => {
  it("renders for a redraft owner with no outlook", () => {
    render(<OwnerDeepDive leagueId="lg" detail={detail({ outlook: null })} />);
    expect(screen.getByRole("button", { name: /draft/i })).toBeTruthy();
  });

  it("is absent when the owner has no drafted picks", () => {
    render(
      <OwnerDeepDive
        leagueId="lg"
        detail={detail({ outlook: null, draft_picks_by_season: {} })}
      />,
    );
    expect(screen.queryByRole("button", { name: /^draft$/i })).toBeNull();
  });
});
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd web && npx vitest --config tests/vitest.config.ts run tests/draft-tab.test.tsx`
Expected: FAIL — no Draft tab is rendered.

- [ ] **Step 4: Add the tab**

In `web/components/OwnerDeepDive.tsx`, extend `TabKey` with `"draft"` and change the `TABS` array:

```tsx
  const hasDraftPicks = Object.keys(detail.draft_picks_by_season ?? {}).length > 0;
  const TABS: { key: TabKey; label: string; short?: string }[] = [
    { key: "overview", label: "Overview" },
    { key: "record", label: "Track Record", short: "Record" },
    { key: "trades", label: "Trades" },
    // Gated on the picks themselves, NOT on outlook: redraft leagues drop the
    // Outlook tab entirely, which used to take draft grading down with it.
    ...(hasDraftPicks ? [{ key: "draft" as TabKey, label: "Draft" }] : []),
    ...(detail.outlook ? [{ key: "outlook" as TabKey, label: "Outlook" }] : []),
  ];
```

Add the panel next to the existing outlook panel:

```tsx
        {activeTab === "draft" && (
          <PastPicksTable
            bySeason={detail.draft_picks_by_season ?? {}}
            ownerName={detail.owner.owner_name}
          />
        )}
```

Import `PastPicksTable` at the top of the file.

- [ ] **Step 5: Remove it from `FutureDraftTab`**

In `web/components/ownerdeepdive/FutureDraftTab.tsx`, delete the `<PastPicksTable … />` render at line 153, its import at line 6, and the now-unused `draftPicksBySeason` / `ownerName` props. Remove the corresponding props passed from `OwnerDeepDive.tsx:235-237`.

- [ ] **Step 6: Add the new columns to `PastPicksTable`**

In `web/components/ownerdeepdive/PastPicksTable.tsx`:
- Add a `Keeper` chip wherever `roster_status` chips are rendered, shown when `is_keeper` is true.
- Add an `ADP` column and a signed `+/-` delta column, rendered only when at least one row in the season has a non-null `adp`. Signed values get `text-pos` / `text-neg`, matching every other signed figure.
- Hide the value-arc columns (`current_value`, `lowest_value`, `highest_value`, `avg_slot_value`) when every row in the season has `current_value === 0` — redraft chains have no price history, and an all-zero column reads as data. Omit, do not blank.

- [ ] **Step 6b: Make the backend actually send the new fields**

The engine now produces `is_keeper`, `pick_no`, `adp`, `adp_delta`, and `projected_points` on each `drafted_picks` row, but **`api/app/models/owner.py::DraftPickResult` does not declare them and `api/app/services/owner_view.py` builds that model field-by-field without them** — so they never reach the owner page. Typing them in TypeScript without this step produces columns that are permanently `undefined`.

Add to `DraftPickResult` in `api/app/models/owner.py`:

```python
    is_keeper: bool = False
    pick_no: int = 0
    # Null, never 0.0 — an unmatched pick is ungraded on this baseline, which
    # is not the same as scoring zero.
    adp: float | None = None
    adp_delta: float | None = None
    projected_points: float | None = None
```

And in `api/app/services/owner_view.py`, inside the `DraftPickResult(...)` construction (~line 242), add:

```python
            is_keeper=bool(p.get("is_keeper")),
            pick_no=int(p.get("pick_no", 0) or 0),
            adp=p.get("adp"),
            adp_delta=p.get("adp_delta"),
            projected_points=p.get("projected_points"),
```

Note the three optional fields are passed through **unconverted** — `float(p.get("adp") or 0)` would turn an ungraded pick into a first-overall one.

Add a test in `api/tests/` asserting a drafted-pick row carrying `adp=None` round-trips to the owner response as `None` rather than `0.0`.

- [ ] **Step 7: Extend the types**

In `web/lib/types.ts`, add to `DraftPickResult`:

```ts
  is_keeper?: boolean;
  pick_no?: number;
  adp?: number | null;
  adp_delta?: number | null;
  projected_points?: number | null;
```

- [ ] **Step 8: Run the tests**

Run: `cd web && npx vitest --config tests/vitest.config.ts run`
Expected: PASS, including `tests/agate-rules.test.ts`.

- [ ] **Step 9: Commit**

```bash
git add web/components/OwnerDeepDive.tsx \
        web/components/ownerdeepdive/FutureDraftTab.tsx \
        web/components/ownerdeepdive/PastPicksTable.tsx \
        web/lib/types.ts web/tests/draft-tab.test.tsx
git commit -m "feat(web): owner Draft tab, gated on picks not outlook"
```

---

### Task 9: The draft board page

**Files:**
- Create: `web/app/league/[id]/draft/[season]/page.tsx`
- Create: `web/components/DraftBoard.tsx`
- Create: `web/tests/draft-board.test.tsx`
- Modify: `web/lib/types.ts`

**Interfaces:**
- Consumes: `GET /api/league/{id}/draft/{season}` → `DraftBoardResp` (Task 7).
- Produces: `DraftBoardResp`, `DraftBoardPick`, `DraftBoardOwner` TypeScript types.

- [ ] **Step 1: Invoke the styling skill**

Run `agate-styling` and follow it. The board is a ledger: 26px `.ruled` rows, no row borders, zero radius, Geist Mono figures, color only on signed numbers.

- [ ] **Step 2: Write the failing test**

Create `web/tests/draft-board.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { DraftBoard } from "@/components/DraftBoard";

const base = {
  league_id: "lg", season: 2026, seasons: [2026], format: "redraft",
  picks: [{
    player_id: "p1", full_name: "Player One", position: "RB",
    drafter_id: "u1", owner: { user_id: "u1", owner_name: "Alice" },
    round: 1, slot: 1, pick_no: 1, is_keeper: false,
    production_total: 0, adp: 12, adp_delta: -11, projected_points: 210.5,
  }],
  owners: [{
    user_id: "u1", owner: { user_id: "u1", owner_name: "Alice" },
    adp_total_delta: -11, graded_picks: 1, total_picks: 1,
    production_total: 0,
  }],
};

describe("DraftBoard", () => {
  it("renders picks on draft night with no production column", () => {
    render(<DraftBoard leagueId="lg" board={{ ...base, graded: false }} />);
    expect(screen.getByText("Player One")).toBeTruthy();
    expect(screen.queryByText(/total points/i)).toBeNull();
  });

  it("shows production once the class has played", () => {
    render(<DraftBoard leagueId="lg" board={{ ...base, graded: true }} />);
    expect(screen.getByText(/total points/i)).toBeTruthy();
  });

  it("states ADP coverage rather than implying full coverage", () => {
    render(
      <DraftBoard
        leagueId="lg"
        board={{
          ...base, graded: false,
          owners: [{ ...base.owners[0], graded_picks: 11, total_picks: 15 }],
        }}
      />,
    );
    expect(screen.getByText(/11 of 15/)).toBeTruthy();
  });

  it("marks keeper picks", () => {
    render(
      <DraftBoard
        leagueId="lg"
        board={{
          ...base, graded: false,
          picks: [{ ...base.picks[0], is_keeper: true }],
        }}
      />,
    );
    expect(screen.getByText(/keeper/i)).toBeTruthy();
  });
});
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd web && npx vitest --config tests/vitest.config.ts run tests/draft-board.test.tsx`
Expected: FAIL — cannot resolve `@/components/DraftBoard`.

- [ ] **Step 4: Add the types**

In `web/lib/types.ts`:

```ts
export interface DraftBoardPick {
  player_id: string;
  full_name: string;
  position: string;
  drafter_id: string;
  owner?: OwnerRef | null;
  round: number;
  slot: number;
  pick_no: number;
  is_keeper: boolean;
  production_total: number;
  adp?: number | null;
  adp_delta?: number | null;
  projected_points?: number | null;
}

export interface DraftBoardOwner {
  user_id: string;
  owner?: OwnerRef | null;
  adp_total_delta?: number | null;
  graded_picks: number;
  total_picks: number;
  production_total: number;
}

export interface DraftBoardResp {
  league_id: string;
  season: number;
  seasons: number[];
  graded: boolean;
  format: string;
  picks: DraftBoardPick[];
  owners: DraftBoardOwner[];
}
```

- [ ] **Step 5: Build the component**

Create `web/components/DraftBoard.tsx`. Requirements, all enforced by the tests above:

- An owner summary section listing each owner's ADP total delta, with coverage rendered literally as `{graded_picks} of {total_picks}`.
- A picks ledger in draft order: pick number, owner, player, position, then ADP and the signed delta when any pick has an `adp`, then `projected_points` when any pick has one.
- A **Total Points** column rendered **only when `board.graded` is true**. Pre-production it is absent, not zero.
- A `Keeper` marker on `is_keeper` picks.
- A season selector across `board.seasons` linking to `/league/{leagueId}/draft/{season}`.
- Signed figures use `text-pos` / `text-neg`; every other figure is plain ink.
- Reuse existing Agate primitives from `web/components/agate/` rather than inventing new ones.

- [ ] **Step 6: Build the page**

Create `web/app/league/[id]/draft/[season]/page.tsx` following the shape of `web/app/league/[id]/gm/page.tsx` — same auth, same fetch-through-proxy pattern, same cold-cache handling. On a 404 from the endpoint, render the empty state naming the seasons that do exist.

- [ ] **Step 7: Run the tests**

Run: `cd web && npx vitest --config tests/vitest.config.ts run`
Expected: PASS, including `tests/agate-rules.test.ts`.

- [ ] **Step 8: Commit**

```bash
git add web/app/league/\[id\]/draft web/components/DraftBoard.tsx \
        web/lib/types.ts web/tests/draft-board.test.tsx
git commit -m "feat(web): league-wide draft board"
```

---

### Task 10: Dashboard lead covers the pre/post-draft window

**Files:**
- Modify: `web/components/HeadlineMoves.tsx:191-230, 335-347`
- Create: `web/tests/draft-lead.test.tsx`

**Interfaces:**
- Consumes: `DashboardResp.draft_review` with the new `graded: boolean` (Task 4), `DashboardResp.phase`.
- Produces: no new exports.

**Why this task exists:** `phase: "draft"` falls through `draftReviewContent` → `tradeOfWeekContent` when there is no gradeable prior class. A first-season redraft league has neither, so the lead is blank through its draft window.

- [ ] **Step 1: Invoke the styling skill**

Run `agate-styling`. The lead's fixed three-figure skeleton must hold at every width and in every phase — the page must not reflow across the season.

- [ ] **Step 2: Write the failing test**

Create `web/tests/draft-lead.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { HeadlineMoves } from "@/components/HeadlineMoves";

const dash = (over: Record<string, unknown> = {}) => ({
  league_id: "lg", phase: "draft", phase_season: 2026,
  trades: [], standings: [], owners: {},
  ...over,
}) as never;

describe("draft-window lead", () => {
  it("still renders three figures with no prior class and no trades", () => {
    const { container } = render(
      <HeadlineMoves data={dash({ draft_review: null })} leagueId="lg" />,
    );
    expect(container.textContent).toBeTruthy();
    expect(screen.queryByText(/undefined/i)).toBeNull();
  });

  it("reports an ungraded class as results, not as a grade", () => {
    render(
      <HeadlineMoves
        data={dash({
          draft_review: {
            season: 2026, graded: false, best: null, worst: null,
            beat_slot: 0, total: 24,
          },
        })}
        leagueId="lg"
      />,
    );
    expect(screen.queryByText(/best pick/i)).toBeNull();
  });
});
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd web && npx vitest --config tests/vitest.config.ts run tests/draft-lead.test.tsx`
Expected: FAIL — the ungraded branch either throws on the null `best` or falls through to trade-of-the-week.

- [ ] **Step 4: Handle the ungraded state**

In `web/components/HeadlineMoves.tsx`, in `draftReviewContent`, before reading `best`/`worst`:

```tsx
  // A class that has completed but not played yet: the results are real, the
  // grade is not. Naming a "best pick" out of an all-zero field would invent
  // one, so report the class instead and let the board carry the detail.
  if (review && !review.graded) {
    return {
      kicker: "Draft",
      phase: `${review.season} draft`,
      headline: `The ${review.season} draft is in the books — ${review.total} picks.`,
      href: `/league/${leagueId}/draft/${review.season}`,
      figures: [
        { label: "Picks made", text: String(review.total) },
        { label: "Class", text: String(review.season) },
        { label: "Graded", text: "After week 1" },
      ],
    };
  }
```

Keep the existing `if (!review) return tradeOfWeekContent(...)` fallback below it, unchanged.

- [ ] **Step 5: Run the tests**

Run: `cd web && npx vitest --config tests/vitest.config.ts run`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add web/components/HeadlineMoves.tsx web/tests/draft-lead.test.tsx
git commit -m "feat(web): draft-window lead covers a just-completed class"
```

---

### Task 11: Documentation

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Replace the draft-grading content in the "How past picks panned out" bullet**

Add a new bullet under Key conventions:

```markdown
- **Draft grading (all formats):** `engine/draft_class.py::build_draft_classes` decides
  once what each Sleeper draft *is* — every format question about a draft is answered
  there and nowhere else. Selection keys on `settings.player_type` (**1 = rookies only,
  0 = all players**), not on the season: dynasty grades rookie classes and discards the
  startup, while **redraft and keeper grade every season's full draft including year
  one**. An auction is ingested with `gradeable=False` — its `pick_no` is chronological,
  so a slot delta would be noise. Grading runs on **three independent baselines, never
  blended**: the league-native peer delta (`draft_signals.py::draft_skill`, available in
  every format, and **the only one that feeds Franchise Rating**), the ADP delta, and the
  projection delta. ADP and projected points both come from
  `SleeperClient.get_projections` — one call, native Sleeper `player_id`, no crosswalk,
  covering K and DEF which FantasyCalc's redraft set does not. **`999.0` is the undrafted
  sentinel and must be filtered** (`engine/draft_baselines.py::ADP_UNDRAFTED`) — same trap
  as DynastyProcess's `"NA"`. **ADP is pinned to each draft's own date, not to refresh
  time** — `api/app/services/adp_snapshot_store.py` writes a dated daily snapshot
  (`adp/daily/YYYY-MM-DD.json`, the `KtcSnapshotStore` pattern) on every refresh, and
  `resolve_for_draft(draft_id, drafted_on)` picks the snapshot on-or-before that draft's
  `last_picked` date, **never after**, then freezes it write-once per `draft_id`. A league
  drafting Aug 1 and one drafting Aug 26 face different markets and must grade against
  their own; capturing at refresh time would have stamped August ADP on a May draft.
  Grading against live ADP is grading against hindsight, so ADP columns work **going
  forward only** — a draft predating the first daily snapshot has no baseline, permanently,
  and grades on the peer baseline alone. **Keeper picks are shown but never scored** — a keep is not a
  draft decision, and leaving it in the peer group raises what its round is expected to
  return. Results and grades have **different availability dates**: `build_draft_review`
  and the board return `graded: False` with the picks intact for a class that has not
  played, rather than None. Surfaces: the league-wide board
  (`web/app/league/[id]/draft/[season]/page.tsx`), the owner **Draft** tab (gated on
  `draft_picks_by_season`, **not** on `outlook` — that gate is what used to hide draft
  grading from redraft leagues entirely), and the draft-window dashboard lead.
```

- [ ] **Step 2: Run the full suite**

Run: `pytest tests/ -q && pytest api/tests -q && cd web && npx vitest --config tests/vitest.config.ts run`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: format-aware draft grading contract"
```

---

## Post-implementation verification

These cannot be done before the redraft league's draft completes (~2026-08-16) and are **not** part of any task above. Record them as follow-up work:

1. **Pre-draft fixture capture** — before the draft, record the redraft league's `/drafts` payload and confirm `settings.player_type == 0`, the `type`, and the chain shape. This window does not reopen.
2. **Draft-night verification** — confirm the board renders results, the ADP snapshot was captured (`adp/{draft_id}.json` exists in the cache volume), and the dashboard lead shows the class rather than falling through.
3. **Week 1 verification** — confirm `graded` flips true and the production columns appear.
4. **Franchise Rating regression** — confirm dynasty owners' ratings are unchanged, since the blend axis path is byte-identical.

## Known gaps carried forward

- No rookie-draft ADP: `adp_dynasty` and `adp_rookie` are unpopulated in the source, so dynasty grades on the peer baseline alone.
- No retroactive ADP: drafts completed before this ships have no snapshot, permanently.
- Redraft traded picks still price at 0 (KTC skipped for redraft chains) — untouched, separately deferred.
- FantasyCalc's `numTeams` / `ppr` remain hardcoded — untouched, and now irrelevant to draft grading.
