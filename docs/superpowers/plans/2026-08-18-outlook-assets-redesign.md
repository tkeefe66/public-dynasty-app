# Assets-led Outlook Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Retire the independent Strength × Trajectory window model and rebuild the owner page's Outlook tab as the Franchise Rating's Assets pillar, with the competitive-window stage derived from the rating itself.

**Architecture:** One new pure function (`gm_rating.py::rating_to_stage`) bands the v2 composite the same way `rating_to_letter` bands it, so a league has exactly one model. `build_dynasty_outlook` sheds six parameters and three fields and becomes an age-profile / draft-capital / draft-needs builder. `window` stops being persisted and becomes a read-time derivation in `owner_view` and `aggregations`. The Outlook tab is rebuilt as five sections against the Assets pillar breakdown the `/gm` response already carries.

**Tech Stack:** Python 3.11 (engine + FastAPI), pytest; Next.js 14 App Router + TypeScript + Tailwind against `.design/` tokens, vitest.

**Spec:** `docs/superpowers/specs/2026-08-18-outlook-assets-redesign-design.md` (rev 3)

**QA gates (definition of done):** https://claude.ai/code/artifact/b9cf990a-764f-41ba-96b1-bee45aac4352 — 54 checks, 32 blockers.
**Approved design (Lead B ships):** https://claude.ai/code/artifact/94d3e2cd-1197-4005-9a08-9cc2f535bb6e
**Pre-change baseline:** `docs/superpowers/baselines/2026-08-18-outlook-window-before.json` — 12 owners' `window`, both axis scores, every per-input contribution. These values exist nowhere else after Task 3.

---

## Global Constraints

- **Branch:** `outlook-assets-redesign`. **Never push to `main`** — Railway auto-deploys from it.
- **Engine tests:** `pytest tests/` from the repo root. Bare `pytest` breaks (`api/tests` and `tests/` are both packages named `tests`).
- **API tests:** `cd api && pytest tests/`.
- **Frontend tests:** `cd web && npx vitest --config tests/vitest.config.ts run`. Bare `npx vitest run` silently loads **no** config and dies on JSX.
- **`SCHEMA_VERSION` stays 17.** No bump. A bump 409s every league until rebuild for no correctness gain.
- **Never render "KTC"** in `web/`. It is "Trade Value" / "Value". `furniture-rules.test.ts` has a `ktc` rule.
- **Furniture only** in `web/`: no literal colour, size, weight or duration — tokens from `.design/` via Tailwind. Radius `--radius`/`--radius-sm`/`--radius-pill` only. Seven type sizes only. Mono for every figure and label. Section headings mixed case, never uppercase. Solid panels draw their own row rules. Figures reconcile with the rows beneath them.
- **Stage vocabulary (the only five, low to high):** `Rebuilding` · `Retooling` · `Competing` · `Contending` · `Dynasty`.
- **Stage band edges as ratings:** `1748` / `1582` / `1418` / `1252`. Derived, never hardcoded.
- **The CLI exports (`html_report.py`, `google_docs.py`) DROP the Dynasty Window chip permanently.** They have no Franchise Rating in scope. Decided; do not add a second stage derivation.
- **`assets_signal_ranks` and `window` are read-time only.** Neither is written to any `ChainCacheEntry` field.
- **Prove tests bite.** For any test asserting an ordering, a boundary, or a filter, mutate the implementation out and confirm red before trusting green. Set a **unique** `PYTHONPYCACHEPREFIX` per run (e.g. `/tmp/pycache-$$`) — a *shared* prefix is not enough and produced a phantom result on Task 5. CPython invalidates a `.pyc` on `(mtime, size)`, so a mutate-then-restore cycle that lands in the same clock second with the same byte length is served stale bytecode and the mutation appears not to bite.

---

## Review findings folded into this plan

Two independent sweeps were run per-symbol (not per-file) against the codebase after rev 3. Everything below is **new** relative to the spec's own lists and is already incorporated into the tasks. It is recorded here so the executor does not have to rediscover it.

**Consumers and test files absent from the spec's fallout list:**

1. `web/tests/OwnerDeepDive.test.tsx:86-96` — fixture carries `strength_score`, `trajectory_score`, `window_breakdown`, `strength_inputs`, `trajectory_inputs`.
2. `api/tests/test_owner_view_outlook.py` — the *primary* `OutlookView` test file (`WINDOW_BREAKDOWN` at `:8`, assertions at `:147-180`). Not named anywhere in the spec.
3. `api/tests/services/test_season_ratings_v2.py:12,39,46-65` — imports `_backfill_yoy` and builds a `window_breakdown` fixture. Dies with `_backfill_yoy`.
4. `tests/test_html_report.py:12-15,156-200` — constructs `DynastyOutlook(window=…, trajectory=…)` and `DraftNeed(...)`. All **keyword** args, so Task 4's defaulted `held`/`ideal`/`kind` will NOT break it; only the removed `window=`/`trajectory=` kwargs do. It breaks at construction, not at an assertion, so a search for assertions on those fields misses it.
5. `tests/test_dynasty.py` — the largest single casualty (imports `:8-16`, window unit tests `:64-120`, breakdown tests `:122-230`). Never named in the spec.
6. `api/tests/test_capabilities_api.py:111,141` — asserts `trajectory_score` beyond the `:124-131` block the spec names.
7. `web/components/DashboardSkeleton.tsx:19,116` — imports `FRANCHISE_COLS`/`FRANCHISE_GRID`. Stays correct only because both change together; must be verified, not assumed.

**Sites the spec undercounts inside files it does list:**

8. `html_report.py` touches the stage/trajectory at **nine** sites, not four. The spec never named `:512`, which is the actual chip render: `<span class="chip {{ team.chip_class }}">{{ team.window }}</span>`. Full list in Task 3.
9. `google_docs.py` has **seven**, not four. Full list in Task 3.
10. `cli.py:656-671` — `sorted_by_pts` and `rank_pct_map` exist *only* to feed `projected_rank_pct`. Deleting that parameter orphans ~16 lines the spec's dead-input tail does not list.
11. `MethodologyContent.tsx` — the Window entry sits inside Section 6 "Supporting columns", whose lead paragraph asserts these columns are "**not** part of the Franchise Rating formula". After this change Window *is* derived from the rating, so that sentence becomes false. The spec stopped inside the entry at `:598-604`.
12. `api/app/models/league.py:66-72,83` — the axis-score doc comment cites `WindowSection.tsx`, and the `roster_rank` comment cross-references the deleted fields.
13. `web/lib/types.ts:66-70` — "The four Outlook-derived fields" becomes three.
14. `api/app/services/chain_cache.py:125-127` — the two-`draft_needs` disambiguation comment states the `DraftNeed{position, urgency, reason}` shape and cites `owner_view.py:177`.
15. `StandingsTable.tsx:270-273` (`formatStrengthTrajectory`) and `:629-631` (its cell) are deleted; the spec's "three derived arrays + four grid strings" names neither.

**Design/mechanism gaps:**

16. `ContributionRow` (`RatingBars.tsx:64`) is a **fixed three-column** grid (`168px_1fr_52px`). §2's ledger is five columns. It is not reusable as-is; `DivergeBar` is module-private and is exported in Task 6.
17. `web/lib/window.ts::WINDOW_STAGES` currently holds the **old** five. "Keep it as the design system's five" is a value change, not a keep.
18. The design mock renders needs rows for **full** rooms (WR 5 of 5, QB 2 of 2, urgency "—"). The spec and QA gate 6 both forbid emitting those. The mock is illustrative; the spec wins.
19. `assess_draft_needs` branch 1 (`current_count < _MIN_STARTERS`) is also a strict count shortfall (`held < ideal` always holds there), so pips would read correctly on it. The spec and QA restrict pips to the `ideal_depth` branch. **Following the spec**; flagged as the one place a one-line change would add information.
20. The UI needs a discriminator to know which branch produced a need — `urgency` cannot serve, because both the depth branch and the aging branch emit `"developing"`. Task 4 adds `DraftNeed.kind`. The spec required the behaviour without naming the mechanism.
21. `OutlookView.assets_signal_ranks` duplicates `franchise_rating.pillars["assets"].signal_ranks`, which the same response already carries. Both are built, because QA gate 4 names the `OutlookView` field explicitly.

---

## File structure

**Engine (`src/sleeper_dynasty/`)**

| File | Responsibility after this change |
|---|---|
| `engine/gm_rating.py` | **+** `_STAGE_SD`, `STAGE_BANDS`, `rating_to_stage`. Sits beside `rating_to_letter`, sharing `POINTS_PER_SD` / `REFERENCE_COMPOSITE_SD`. |
| `engine/dynasty.py` | **−** the whole window model. Keeps `AgeProfile`, `DraftCapital`, `DraftNeed`, `analyze_age_profile`, `analyze_draft_capital`, `assess_draft_needs`, `build_dynasty_outlook`. `DraftNeed` gains `held`/`ideal`/`kind`; `DynastyOutlook` drops to three fields. |
| `engine/outlook_build.py` | **−** `window_input_dict`, `roster_value_rank_pct`, the `dc_pct_rank_by_uid` block and four params. **+** `league_avg_age_by_position`; returns a tuple; `outlook_to_dict` takes the league map. |
| `engine/franchise_outlook.py` | `build_franchise_facts` takes `window` as a **parameter** instead of reading it off the blob. |
| `llm/franchise_validation.py` | `_VOCABULARY` swaps the five stage words. |
| `output/html_report.py` | Drops the Window chip and the Trajectory line — nine sites. |
| `output/google_docs.py` | Same — seven sites. |
| `cli.py` | Drops `projected_rank_pct` and the `rank_pct_map` block that fed it. |

**API (`api/`)**

| File | Responsibility after this change |
|---|---|
| `app/models/leaderboard.py` | `PillarBreakdown` **+** `signal_ranks: dict[str, int]`. Public `/gm` shape change. |
| `app/models/owner.py` | `OutlookView` reshaped. `WindowBreakdownView` / `WindowInputView` deleted. `DraftNeedView` **+** `held`/`ideal`/`kind`. `AgeProfileView` **+** `league_avg_age_by_position`. |
| `app/models/league.py` | `StandingRow` **−** `strength_score`/`trajectory_score`; `window` doc rewritten. |
| `app/services/franchise_redesign.py` | `live_ratings` populates `signal_ranks` on every pillar. |
| `app/services/owner_view.py` | Assembles the reshaped `OutlookView`; `window` derived from `gm_row.rating` **after** the rating block resolves. |
| `app/services/aggregations.py` | `StandingRow.window` derived from `ratings`, gated on `_outlooks_apply`. |
| `app/services/refresh_service.py` | **−** `_backfill_yoy` and its call site. |
| `app/services/grader.py` | **−** the dead-signal extraction; **+** `window=` into the facts packet; passes the league age map into `outlook_to_dict`. |

**Frontend (`web/`)**

| File | Responsibility after this change |
|---|---|
| `lib/types.ts` | TS mirror updated: `WindowInput`/`WindowBreakdown` deleted, `OutlookView`/`StandingRow`/`PillarBreakdown`/`DraftNeedView`/`AgeProfileView` updated. |
| `lib/window.ts` | Keeps `WINDOW_STAGES` **with the new five**. `WINDOW_THRESHOLDS`, `WINDOW_INPUT_LABELS`, `formatWindowRaw` deleted. |
| `components/furniture/StageLadder.tsx` | **New.** Port of `.design/components/data/WindowCell.jsx`. |
| `components/RatingBars.tsx` | Exports `DivergeBar` so the Assets ledger can reuse the bar without the 3-column `ContributionRow`. |
| `components/ownerdeepdive/OutlookTab.tsx` | **New.** §1 Hero + §2 Assets ledger, and composes §3/§4/§5. |
| `components/ownerdeepdive/RosterHealthTab.tsx` | Rewritten. Exports `RoomsSection` (§4) + the young-core/aging disclosure. |
| `components/ownerdeepdive/FutureDraftTab.tsx` | Rewritten. Exports `DraftNeedsSection` (§3) and `DraftSection` (§5). |
| `components/ownerdeepdive/WindowSection.tsx` | **Deleted.** |
| `components/OwnerDeepDive.tsx` | The `activeTab === "outlook"` block becomes `<OutlookTab …/>`. |
| `components/StandingsTable.tsx` | Window tooltip + `s/t` column removed across all eight sites. |
| `components/methodology/MethodologyContent.tsx` | Window entry rewritten and relocated out of "not part of the formula". |

---

# Task 1: `rating_to_stage`

Pure. Lands green on its own, touches nothing else.

**Files:**
- Modify: `src/sleeper_dynasty/engine/gm_rating.py` (after `rating_to_letter`, ~`:172`)
- Test: `tests/test_gm_rating_stage.py` (create)

**Interfaces:**
- Consumes: `BASE`, `POINTS_PER_SD` (both already in `gm_rating.py`).
- Produces: `rating_to_stage(rating: int) -> str` returning one of `"Dynasty"`, `"Contending"`, `"Competing"`, `"Retooling"`, `"Rebuilding"`; and `STAGE_BANDS: list[tuple[int, str]]` (points-above-`BASE`, stage), high to low.

- [ ] **Step 1: Write the failing test**

Create `tests/test_gm_rating_stage.py`:

```python
"""Band edges, rounding, and monotonicity for rating_to_stage.

Every edge is tested from BOTH sides. A one-sided edge test passes on an
off-by-one, which is the whole class of bug these bands can have.
"""

import pytest

from sleeper_dynasty.engine.gm_rating import (
    BASE, LETTER_BANDS, POINTS_PER_SD, STAGE_BANDS, rating_to_letter,
    rating_to_stage,
)

STAGES = ["Rebuilding", "Retooling", "Competing", "Contending", "Dynasty"]


def test_band_edges_from_both_sides():
    assert rating_to_stage(1748) == "Dynasty"
    assert rating_to_stage(1747) == "Contending"
    assert rating_to_stage(1582) == "Contending"
    assert rating_to_stage(1581) == "Competing"
    assert rating_to_stage(1418) == "Competing"
    assert rating_to_stage(1417) == "Retooling"
    assert rating_to_stage(1252) == "Retooling"
    assert rating_to_stage(1251) == "Rebuilding"


def test_bands_use_bankers_rounding_and_are_symmetric():
    """Every sd multiple lands on an exact .5 of a point.

    round(82.5) == 82, not 83; a naive int(x + 0.5) gives 83 / -82 and breaks
    the symmetry. The offsets must mirror exactly around BASE.
    """
    offsets = [lo for lo, _ in STAGE_BANDS]
    assert offsets == [248, 82, -82, -248]
    assert offsets[0] == -offsets[3]
    assert offsets[1] == -offsets[2]
    # And they are derived, not typed: 0.90 * 275 == 247.5 -> 248.
    assert round(0.30 * POINTS_PER_SD) == 82
    assert round(0.90 * POINTS_PER_SD) == 248


def test_every_stage_is_reachable():
    """The F-band failure recorded in gm_rating.py, checked for this rail."""
    seen = {rating_to_stage(r) for r in range(800, 2201)}
    assert seen == set(STAGES)


def test_monotone_across_the_whole_clamp_range():
    """rating + 1 can never yield a LOWER rung. This is the invariant rev 1's
    z-pair rule broke: a league-average team outranked a +1.9sd one."""
    prev = -1
    for r in range(800, 2201):
        i = STAGES.index(rating_to_stage(r))
        assert i >= prev, f"rating {r} dropped a rung"
        prev = i


def test_aligned_with_the_letter_scale():
    """The bands are the letter bands' own units, so the alignment is exact,
    not approximate — the Dynasty edge IS the A- edge, and Competing spans
    C- through B-."""
    assert rating_to_letter(1748) == "A-"
    assert rating_to_stage(1748) == "Dynasty"
    assert {rating_to_letter(r) for r in range(1418, 1582)} == {"C-", "C", "C+", "B-"}
    assert {rating_to_stage(r) for r in range(1418, 1582)} == {"Competing"}
    # Shared mechanism: both tables convert sd multiples through POINTS_PER_SD
    # with the same round().
    assert all(isinstance(lo, int) for lo, _ in LETTER_BANDS)


@pytest.mark.parametrize("rating", [800, 2200])
def test_clamp_extremes_resolve(rating):
    assert rating_to_stage(rating) in STAGES
```

- [ ] **Step 2: Run it and verify it fails**

```bash
cd "/Users/tomkeefe/Code Apps/public-dynasty"
pytest tests/test_gm_rating_stage.py -v
```

Expected: collection error — `ImportError: cannot import name 'STAGE_BANDS'`.

- [ ] **Step 3: Implement**

In `src/sleeper_dynasty/engine/gm_rating.py`, immediately after `rating_to_letter` (which ends `return "D-"`), insert:

```python
# (sd multiple, stage), high to low. The competitive-window rail, banded on
# the SAME composite `rating_to_letter` bands and converted through the same
# POINTS_PER_SD, so the two scales cannot drift and no second prior is
# introduced. `else` is "Rebuilding".
#
# Monotone by construction: the rung is a function of one scalar, so a better
# composite can never land on a lower rung. The v1 model this replaces mixed a
# level test with the RELATION `assets_z >= results_z` and put the result on an
# ordered rail, which let a league-average team (+0.1 / +0.2) outrank a
# +1.9 / +1.8 one. Relation rules cannot be monotone on a rail.
#
# Populations against a normal composite (verified 2026-08-18):
# 18.4 / 19.8 / 23.6 / 19.8 / 18.4 % -- 2.2 to 2.8 owners of twelve per rung,
# symmetric. That check is the point of stating it: the F-band note above
# records a band that "could only ever fire by construction or never", and a
# five-rung rail is exactly where that recurs.
#
# The edges align with the letter scale exactly: Dynasty starts on A-, and
# Competing spans C- through B-, containing all of the C band that is
# league-average by definition.
#
# Same caveat as LETTER_BANDS: honestly derived from REFERENCE_COMPOSITE_SD,
# but n=12, one league. Re-measure with the `franchise-rating-calibration`
# skill whenever the tree or the bands move.
_STAGE_SD: list[tuple[float, str]] = [
    (0.90, "Dynasty"), (0.30, "Contending"),
    (-0.30, "Competing"), (-0.90, "Retooling"),
]

STAGE_BANDS: list[tuple[int, str]] = [
    (round(mult * POINTS_PER_SD), stage) for mult, stage in _STAGE_SD
]


def rating_to_stage(rating: int) -> str:
    """Map a league-relative Franchise Rating to its competitive-window stage.

    One of Dynasty / Contending / Competing / Retooling / Rebuilding, high to
    low. This is the ONLY producer of a window stage: the independent
    Strength x Trajectory model that used to answer this question is retired,
    so an owner cannot read one stage on the standings row and another on the
    franchise page.

    Like the letter, the stage is a PERCENTILE WITHIN YOUR LEAGUE, not an
    absolute or cross-league scale.
    """
    delta = rating - BASE
    for lo, stage in STAGE_BANDS:
        if delta >= lo:
            return stage
    return "Rebuilding"
```

- [ ] **Step 4: Run and verify green**

```bash
pytest tests/test_gm_rating_stage.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Prove the tests bite** (QA gate 1, blocker)

```bash
export PYTHONPYCACHEPREFIX=/tmp/pycache-outlook
cp src/sleeper_dynasty/engine/gm_rating.py /tmp/gm_rating.orig.py
```

Run each mutation, confirm **FAIL**, then restore from `/tmp/gm_rating.orig.py` before the next:

| # | Mutation | Must fail |
|---|---|---|
| 1 | `(0.90, "Dynasty")` → `(0.91, "Dynasty")` | `test_band_edges_from_both_sides` |
| 2 | `if delta >= lo:` → `if delta > lo:` | `test_band_edges_from_both_sides` |
| 3 | `round(mult * POINTS_PER_SD)` → `int(mult * POINTS_PER_SD + 0.5)` | `test_bands_use_bankers_rounding_and_are_symmetric` |
| 4 | swap the two stage **names** in `_STAGE_SD`, leaving the sd multiples in descending order | `test_monotone_across_the_whole_clamp_range` (also `test_band_edges_from_both_sides`, `test_aligned_with_the_letter_scale`) |
| 5 | swap the two **entries** (so `-0.30` precedes `0.30` in list order) | `test_every_stage_is_reachable` — the first-match scan then skips a rung entirely. Note this does NOT break monotonicity: the surviving rungs stay in order, which is exactly why reachability needs its own test |

```bash
cp /tmp/gm_rating.orig.py src/sleeper_dynasty/engine/gm_rating.py
pytest tests/test_gm_rating_stage.py -q   # green again
```

- [ ] **Step 6: Run the full engine suite**

```bash
pytest tests/ -q
```

Expected: no new failures (this task adds a symbol; it removes nothing).

- [ ] **Step 7: Commit**

```bash
git add src/sleeper_dynasty/engine/gm_rating.py tests/test_gm_rating_stage.py
git commit -m "feat(gm-rating): rating_to_stage — the window stage becomes a band on the composite"
```

---

# Task 2: Facts-packet parameterisation + validator vocabulary

Closes the one stale-read path **before** the deletion. Lands green alone: the blob still carries `window`, we simply stop reading it.

**Files:**
- Modify: `src/sleeper_dynasty/engine/franchise_outlook.py:43-93`
- Modify: `src/sleeper_dynasty/llm/franchise_validation.py:80-82`
- Modify: `api/app/services/grader.py` (~`:1880-1905`)
- Test: `tests/test_franchise_outlook.py` (extend; create if absent)

**Interfaces:**
- Consumes: `rating_to_stage` (Task 1).
- Produces: `build_franchise_facts(..., window: str = "")` — `window` is now a **keyword parameter**, never read off `outlook`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_franchise_outlook.py` (create the file with these imports if it does not exist):

```python
from sleeper_dynasty.engine.franchise_outlook import build_franchise_facts


def _stale_blob() -> dict:
    """A pre-feature serialized outlook: it still carries a RETIRED stage."""
    return {
        "window": "Peaking",
        "trajectory": "Strong roster but aging (avg 27.4)...",
        "age_profile": {"core_young": [], "aging_risks": []},
        "draft_capital": {"status": "pick-rich", "net_vs_average": 2.0},
        "draft_needs": [{"position": "RB", "urgency": "immediate", "reason": "x"}],
    }


def test_a_stale_blob_cannot_leak_a_retired_stage_into_the_packet():
    """The ONE stale-read path the no-bump decision leaves open. `window` is a
    parameter; the blob's own key is never consulted."""
    facts = build_franchise_facts(
        user_id="u1", owner_name="Tom", team_name=None,
        outlook=_stale_blob(), roster_rank={"rank": 3, "of": 12},
        signature_trade=None, window="Contending",
    )
    assert facts.window == "Contending"
    assert "Peaking" not in str(facts.to_dict())


def test_an_unrated_owner_sends_no_window_at_all():
    """window="" is pruned by FranchiseFacts.to_dict, so the writer is never
    handed an empty stage to reach for."""
    facts = build_franchise_facts(
        user_id="u1", owner_name="Tom", team_name=None,
        outlook=_stale_blob(), roster_rank=None,
        signature_trade=None, window="",
    )
    assert facts.window == ""
    assert "window" not in facts.to_dict()
```

And in `tests/test_franchise_validation.py` (create if absent):

```python
from sleeper_dynasty.llm.franchise_validation import _VOCABULARY


def test_vocabulary_carries_the_live_stages_and_none_of_the_retired_ones():
    for live in ("retooling", "contending", "competing", "dynasty", "rebuilding"):
        assert live in _VOCABULARY
    for retired in ("now", "peaking", "ascending", "descending"):
        assert retired not in _VOCABULARY
```

- [ ] **Step 2: Run and verify it fails**

```bash
pytest tests/test_franchise_outlook.py tests/test_franchise_validation.py -v
```

Expected: `TypeError: build_franchise_facts() got an unexpected keyword argument 'window'`, and the vocabulary test fails on `"now"`.

- [ ] **Step 3: Parameterise the packet**

In `src/sleeper_dynasty/engine/franchise_outlook.py`, add `window` to the signature and change the field assignment:

```python
def build_franchise_facts(
    *,
    user_id: str,
    owner_name: str,
    team_name: str | None,
    outlook: dict,
    roster_rank: dict | None,
    signature_trade: str | None,
    window: str = "",
    league_format: str = "dynasty",
    young_core_share: float | None = None,
    value_by_player: dict[str, float] | None = None,
) -> FranchiseFacts:
```

Extend the docstring's "what is NOT read off the outlook" note:

```python
    """Assemble FranchiseFacts from the serialized outlook dict (outlook_to_dict).

    Note what is *not* read off the outlook: ``trajectory``, ``overall_avg_age``
    and — since the Assets-led redesign — ``window``.

    ``window`` is a PARAMETER, not a blob read, and that is load-bearing. The
    stage is now derived from the Franchise Rating (gm_rating.rating_to_stage),
    the redesign shipped without a SCHEMA_VERSION bump, and a pre-feature blob
    still carries a RETIRED stage string ("Peaking"). Reading it here would
    feed a word the validator's _VOCABULARY has just dropped into a packet the
    validator then checks. Pass "" for an unrated owner: FranchiseFacts.to_dict
    prunes it, so the writer is handed no stage rather than an empty one.

    ``trajectory`` and ``overall_avg_age`` are both mean roster age, which the
    v2 rating dropped because a mean measures bench filler rather than the
    core. Sending it produced prose that called a roster "trending downward" in
    the same sentence as its "legitimate young core". ``young_core_share`` —
    the value-weighted signal the grade actually scores — is threaded in
    instead.
    """
```

And in the returned `FranchiseFacts(...)`, replace:

```python
        window=outlook.get("window", ""),
```

with:

```python
        window=window,
```

- [ ] **Step 4: Swap the validator vocabulary**

In `src/sleeper_dynasty/llm/franchise_validation.py`, replace lines `:81-82`:

```python
    # Window labels (engine/dynasty.py::classify_window).
    "Competing", "Now", "Peaking", "Rebuilding", "Ascending", "Descending",
```

with:

```python
    # Window stages (engine/gm_rating.py::rating_to_stage). "Dynasty" is
    # already listed under League formats below and is not repeated.
    #
    # Severity here is LOW, and only because the facts packet keeps `window`:
    # _packet_tokens allows the subject's own stage straight off
    # FranchiseFacts.window, so this list only has to cover a DIFFERENT owner's
    # stage. Dropping `window` from the packet would invert that and make the
    # model fail validation for naming its own stage.
    "Competing", "Contending", "Retooling", "Rebuilding",
```

- [ ] **Step 5: Pass the derived stage from the grader**

In `api/app/services/grader.py`, in the `facts_by_owner` loop (~`:1885-1905`). Immediately **before** the loop, add:

```python
            # The stage is derived from this league's own Franchise Rating —
            # there is no second window model any more. `entry` is already
            # constructed above, so live_ratings is in scope. An owner with no
            # completed season is absent from live_ratings and gets "", which
            # FranchiseFacts.to_dict prunes.
            from app.services.franchise_redesign import live_ratings
            from sleeper_dynasty.engine.gm_rating import rating_to_stage
            try:
                _fr_ratings = live_ratings(entry)
            except Exception:
                log.exception("stage derivation skipped; packets carry no window")
                _fr_ratings = {}
```

Then inside the loop, add the argument to the `build_franchise_facts(...)` call:

```python
                    window=(
                        rating_to_stage(_fr_ratings[uid]["rating"])
                        if uid in _fr_ratings else ""
                    ),
```

- [ ] **Step 6: Run and verify green**

```bash
pytest tests/test_franchise_outlook.py tests/test_franchise_validation.py -v
pytest tests/ -q
cd api && pytest tests/ -q && cd ..
```

Expected: the new tests pass; existing suites unchanged (`build_franchise_facts` keeps a defaulted `window`, so no other caller breaks).

- [ ] **Step 7: Prove the stale-read test bites**

```bash
export PYTHONPYCACHEPREFIX=/tmp/pycache-outlook
# revert the one line
sed -i '' 's/^        window=window,$/        window=outlook.get("window", ""),/' \
  src/sleeper_dynasty/engine/franchise_outlook.py
pytest tests/test_franchise_outlook.py -q     # MUST FAIL
sed -i '' 's/^        window=outlook.get("window", ""),$/        window=window,/' \
  src/sleeper_dynasty/engine/franchise_outlook.py
pytest tests/test_franchise_outlook.py -q     # green
```

- [ ] **Step 8: Commit**

```bash
git add src/sleeper_dynasty/engine/franchise_outlook.py \
        src/sleeper_dynasty/llm/franchise_validation.py \
        api/app/services/grader.py \
        tests/test_franchise_outlook.py tests/test_franchise_validation.py
git commit -m "fix(llm): window is a facts-packet parameter, not a blob read

Closes the one stale-read path the no-bump decision leaves open: a
pre-feature blob still carries a retired stage, and the validator has
just dropped that word."
```

---

# Task 3: The engine deletion

**UNSPLITTABLE.** `build_dynasty_outlook` is the only producer of `DynastyOutlook`, so the moment the window model goes it takes both CLI export paths and six test files with it. One commit.

**Files:**
- Modify: `src/sleeper_dynasty/engine/dynasty.py` — delete `:285-424` (the window model), `:530-582` (`_describe_trajectory`), rewrite `build_dynasty_outlook` `:592-700`, trim `DynastyOutlook` `:79-92`
- Modify: `src/sleeper_dynasty/engine/outlook_build.py` — delete `roster_value_rank_pct`, `window_input_dict`, the `dc_pct_rank_by_uid` block, four params, three serialized keys
- Modify: `src/sleeper_dynasty/cli.py:656-685`
- Modify: `src/sleeper_dynasty/output/html_report.py` — nine sites
- Modify: `src/sleeper_dynasty/output/google_docs.py` — seven sites
- Modify: `api/app/services/grader.py:1300-1324`
- Modify: `api/app/services/refresh_service.py:99-155,174-178`
- Modify (pre-flight ruling, pulled forward from Task 5): `api/app/models/owner.py:96-121`, `api/app/models/league.py:66-83`, `api/app/services/owner_view.py:8,186-207`, `api/app/services/aggregations.py:802-804`
- Rewrite: `tests/test_dynasty.py`, `tests/test_outlook_build.py`, `tests/test_html_report.py`
- Delete: `api/tests/test_refresh_service.py:81-141` (the `_backfill_yoy` tests) and `api/tests/services/test_season_ratings_v2.py`'s `_backfill_yoy` test

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `DynastyOutlook(age_profile: AgeProfile, draft_capital: DraftCapital, draft_needs: list[DraftNeed])` — three fields, no defaults.
  - `build_dynasty_outlook(roster, roster_players, traded_picks, position_rankings, total_rosters, num_rounds=4) -> DynastyOutlook`
  - `build_outlooks_by_owner(*, rosters, players, traded_picks, positions, ktc_value_by_player, roster_to_user, total_rosters, num_rounds=4) -> dict[str, DynastyOutlook]` (the tuple return arrives in Task 4)
  - `outlook_to_dict(outlook, as_of=None) -> dict` — no `window`, `trajectory`, `strength_score`, `trajectory_score`, `window_breakdown`
  - `OutlookView(age_profile, draft_capital, draft_needs)` — temporarily three fields; Task 5 adds the new ones. `WindowBreakdownView` / `WindowInputView` deleted.
  - `StandingRow` without `strength_score` / `trajectory_score`. `StandingRow.window` still reads the blob via `.get()`, so it degrades to `None` after a refresh rather than raising — Task 5 makes it the derived value.

- [ ] **Step 1: Rewrite `tests/test_dynasty.py`'s window half first**

Delete these from `tests/test_dynasty.py`:
- imports `classify_window`, `compute_strength_score`, `compute_trajectory_score`, `strength_inputs`, `trajectory_inputs` (`:8-16`)
- the `# --- compute_strength_score ---` block through the end of the `classify_window` tests (`:64-120`)
- every assertion touching `strength_score`, `trajectory_score`, `window`, `trajectory`, `window_breakdown` (`:122-230`), including `_outlook_with_breakdown`

Replace the outlook-orchestrator tests with:

```python
def test_build_dynasty_outlook_returns_the_three_surviving_fields():
    outlook = _build()          # existing helper, minus the deleted kwargs
    assert isinstance(outlook, DynastyOutlook)
    assert isinstance(outlook.age_profile, AgeProfile)
    assert outlook.draft_capital.status in {"pick-rich", "neutral", "pick-poor"}
    assert isinstance(outlook.draft_needs, list)


def test_the_window_model_is_gone_from_the_object():
    outlook = _build()
    for dead in ("window", "trajectory", "strength_score",
                 "trajectory_score", "window_breakdown"):
        assert not hasattr(outlook, dead), f"{dead} survived the deletion"
```

- [ ] **Step 2: Run it and verify it fails**

```bash
pytest tests/test_dynasty.py -v
```

Expected: `test_the_window_model_is_gone_from_the_object` FAILS — `window` still exists.

- [ ] **Step 3: Delete the window model from `dynasty.py`**

Delete outright, in this order (bottom-up keeps line numbers stable):

1. `_describe_trajectory` — the whole function and its `# --- Trajectory description ---` banner (`:530-582`).
2. `classify_window` (`:380-404`).
3. `compute_trajectory_score` (`:361-376`).
4. `compute_strength_score` (`:351-358`).
5. `trajectory_inputs` (`:325-348`).
6. `strength_inputs` (`:311-322`).
7. `WindowBreakdown` (`:298-308`) and `WindowInput` (`:285-295`), and the `# --- Window classification ---` banner above them.

Then trim `DynastyOutlook` (`:79-92`) to:

```python
@dataclass
class DynastyOutlook:
    """Roster-shape reading for a single roster: how old it is, what picks it
    holds, and what it is short of.

    It carries NO competitive-window stage. The stage is
    `engine/gm_rating.py::rating_to_stage`, a band on the Franchise Rating
    composite — one model, not two arithmetics over the same evidence, free to
    disagree on adjacent tabs of one page. `ktc_position_rankings` still feeds
    `assess_draft_needs`, so what is left is coherent on its own.
    """

    age_profile: AgeProfile
    draft_capital: DraftCapital
    draft_needs: list[DraftNeed]
```

- [ ] **Step 4: Rewrite `build_dynasty_outlook`**

Replace `:592-700` entirely with:

```python
def build_dynasty_outlook(
    roster: Roster,
    roster_players: list[Player],
    traded_picks: list[DraftPick],
    position_rankings: dict[str, list[str]],
    total_rosters: int,
    num_rounds: int = 4,
) -> DynastyOutlook:
    """Build the roster-shape reading for a single roster.

    Six parameters died with the window model — `projected_rank_pct`,
    `ktc_value_by_player`, `draft_skill`, `playoff_rate`, `yoy_rating_delta`
    and `draft_capital_pct_rank`. They are gone rather than defaulted: a
    signature that still names an input nothing reads is a signature that
    lies about what the function needs.

    Args:
        roster: The roster to analyze.
        roster_players: Player objects for all players on the roster.
        traded_picks: All traded pick records across the league.
        position_rankings: position -> ordered list of player_ids (best first).
        total_rosters: Number of teams in the league.
        num_rounds: Number of draft rounds per season.

    Returns:
        DynastyOutlook for the roster.
    """
    logger.info("Building dynasty outlook for roster %d", roster.roster_id)

    age_profile = analyze_age_profile(roster_players)

    draft_capital = analyze_draft_capital(
        roster_id=roster.roster_id,
        traded_picks=traded_picks,
        total_rosters=total_rosters,
        num_rounds=num_rounds,
    )

    draft_needs = assess_draft_needs(
        roster_players=roster_players,
        position_rankings=position_rankings,
        age_profile=age_profile,
        total_rosters=total_rosters,
    )

    logger.info(
        "Dynasty outlook for roster %d: %d needs, capital %s",
        roster.roster_id, len(draft_needs), draft_capital.status,
    )
    return DynastyOutlook(
        age_profile=age_profile,
        draft_capital=draft_capital,
        draft_needs=draft_needs,
    )
```

Check the tail of the old function for a trailing `return outlook` / log line and remove it with the rest. Then remove now-unused imports at the top of `dynasty.py` if `date` or `CORE_YOUNG_MAX_AGE` become unreferenced — run `python -c "import sleeper_dynasty.engine.dynasty"` and a linter pass to confirm.

- [ ] **Step 5: Strip `outlook_build.py`**

1. Delete `roster_value_rank_pct` entirely (`:38-48`) — its only consumer was `projected_rank_pct`.
2. Delete `window_input_dict` entirely (`:139-147`) — the spec is explicit that this is deleted, not edited; its only argument is a `WindowInput` and its only other caller is `_backfill_yoy`, which dies in Step 9.
3. In `build_outlooks_by_owner`: delete the four params `draft_skill_by_uid`, `playoff_rate_by_uid`, `yoy_rating_by_uid`, `outlook_signals_by_uid`; delete the `rank_pct = roster_value_rank_pct(rv_by_roster)` line and the `rv_by_roster` dict that only fed it; delete the whole `dc_pct_rank_by_uid` block (`:90-105`); and reduce the `build_dynasty_outlook(...)` call to:

```python
        out[uid] = build_dynasty_outlook(
            roster=r,
            roster_players=roster_players,
            traded_picks=traded_picks,
            position_rankings=rankings,
            total_rosters=total_rosters,
            num_rounds=num_rounds,
        )
```

4. In `outlook_to_dict`, delete the `window`, `trajectory`, `strength_score`, `trajectory_score` and `window_breakdown` keys. The dict starts at `"age_profile"`.
5. Update the module docstring: it currently says "we substitute KTC value for both inputs `build_dynasty_outlook` needs: position rankings (by KTC desc) and `projected_rank_pct`". Only the rankings survive:

```python
"""Offseason-safe construction of dynasty outlooks for the API refresh.

The CLI builds position rankings from Monte-Carlo projections; those don't
exist in the offseason. Here we substitute KTC value: position rankings ranked
by KTC desc. That is the only input ``build_dynasty_outlook`` needs that is not
already on the roster — the competitive-window model that used to need four
more is retired (see engine/gm_rating.py::rating_to_stage). Pure and
unit-tested.
"""
```

- [ ] **Step 6: Trim the CLI**

In `src/sleeper_dynasty/cli.py`, delete the now-dead `sorted_by_pts` / `rank_pct_map` block (`:659-671` — it exists **only** to feed `projected_rank_pct`) and drop the argument from the call:

```python
            outlook = build_dynasty_outlook(
                roster=roster,
                roster_players=roster_players,
                traded_picks=traded_picks,
                position_rankings=position_rankings,
                total_rosters=league.total_rosters,
                num_rounds=4,
            )
```

Verify `sim_result` is still referenced elsewhere in the function (it is — `report.generate(sim_result=…)`) before deleting anything above it.

- [ ] **Step 7: Strip `html_report.py` — all nine sites**

| Site | Action |
|---|---|
| `:9` module docstring "…and dynasty trajectory." | Reword: "…draft capital and draft needs." |
| `:63-70` `WINDOW_CHIP_CLASSES` | Delete the dict and its comment. |
| `:365-373` `.trajectory { … }` CSS block | Delete. |
| `:375-390` `/* ----- Dynasty window chips ----- */` + `.chip-*` rules | Delete the whole block **including** `.chip-unknown`. Keep the base `.chip` rule only if another feature uses it — grep `class="chip` first; if the window chip is its only user, delete `.chip` too. |
| `:496` prose "…trajectory. Cards ordered by…" | Reword to drop "trajectory". |
| `:512` `<span class="chip {{ team.chip_class }}">{{ team.window }}</span>` | **Delete the line.** This is the actual render and the spec never named it. |
| `:627-628` `{% if team.trajectory %}<div class="trajectory">…` | Delete the `if`/`endif` block. |
| `:829-830` `window = outlook.window …` / `chip_class = …` | Delete both lines. |
| `:931`, `:943` `"window": window,` / `"trajectory": …` | Delete both dict keys. |

Add a one-line comment where the chip used to sit at `:512`. It **must be a Jinja comment (`{# … #}`), not an HTML comment** — an HTML comment survives rendering and would ship the words "Dynasty Window" into every report, failing Step 10's own `assert "Dynasty Window" not in html`:

```
          {# No Dynasty Window chip: the stage is a band on the Franchise
             Rating (engine/gm_rating.py::rating_to_stage) and the CLI's
             Monte-Carlo pipeline has no rating in scope. Giving this export
             its own second derivation would rebuild the two-models problem
             the Assets-led Outlook redesign exists to delete. #}
```

Note `.chip` itself has a second user — `:492` renders `class="chip {{ team.outlook_class }}"` for the unrelated season-outlook chip — so the base `.chip` rule stays; only `.chip-competing`…`.chip-unknown` go.

- [ ] **Step 8: Strip `google_docs.py` — all seven sites**

| Site | Action |
|---|---|
| `:114-119` `# Window -> chip color…` + the map | Delete. |
| `:819` comment mentioning "dynasty-window chips" | Reword to drop it. |
| `:1052` prose "trajectory. Teams ordered by…" | Reword to drop "trajectory". |
| `:1106` `# Record + window chip line.` | Reword to `# Record line.` |
| `:1110` `chip_text = outlook.window if outlook else "Unclassified"` | Delete, and every downstream use of `chip_text`. |
| `:1115` `["Record", "Dynasty Window", "Outlook"]` | Drop `"Dynasty Window"` and the corresponding value cell. |
| `:1260-1262` `f"Trajectory: {outlook.trajectory}"` and its `# Trajectory note.` | Delete. |

Add the same one-line rationale comment near `:1106`.

- [ ] **Step 9: Delete `_backfill_yoy` and strip the grader**

In `api/app/services/refresh_service.py`:
- Delete `_backfill_yoy` entirely (`:99-155`).
- Delete its call site (`:174-178`) and the comment that references the docstring.
- **Do NOT delete `entry.season_ratings = compute_season_ratings(entry)`** above it. The spec calls this "the unconditional `= {}` overwrite" — that describes its *result* under v2, not the statement. It is the field's **sole writer**, `aggregations.py` references `season_ratings` seven times, and deleting it would leave `compute_season_ratings` uncalled. Out of scope for this task, and removing the only writer of a field seven sites read is a larger change than deleting `_backfill_yoy` requires.

In `api/app/services/grader.py` (`:1300-1324`):
- Delete `_draft_skill_by_uid` and `_playoff_rate_by_uid` and the `# Extract signals for two-axis Window scoring.` comment.
- Delete the four dead kwargs from the `build_outlooks_by_owner(...)` call: `draft_skill_by_uid`, `playoff_rate_by_uid`, `yoy_rating_by_uid={}`, `outlook_signals_by_uid`.
- Delete the `ktc_value_by_player=ktc_floats` argument only if `build_outlooks_by_owner` still needs it — it **does** (position rankings), so keep it.

*(The `chain_cache.py:125-127` comment edit moved to Task 4 — see the pre-flight ruling. Writing it here would commit a comment describing `held`/`ideal`/`kind` a whole task before those fields exist.)*

- [ ] **Step 9b: Delete the API models the blob keys fed** *(pre-flight ruling — pulled forward from Task 5)*

`outlook_to_dict` no longer emits `window`, `trajectory`, `strength_score`, `trajectory_score` or `window_breakdown`, and `owner_view.py:194` reads the first two by **bracket access** — so a freshly written blob would `KeyError`. The existing tests hand-build fixture dicts that still contain those keys, so the suite would stay green while the real read path was broken. The API model is a direct consumer of the deleted blob keys, so it belongs in this deletion. Task 5 is then purely additive.

In `api/app/models/owner.py`:
- Delete `WindowInputView` (`:96-102`) and `WindowBreakdownView` (`:104-110`) entirely.
- From `OutlookView`, delete `window`, `trajectory`, `strength_score`, `trajectory_score`, `window_breakdown`. It temporarily reduces to `age_profile` / `draft_capital` / `draft_needs`; Task 5 adds the new fields back.

In `api/app/services/owner_view.py`:
- Drop `WindowBreakdownView` from the import at `:8`.
- Delete the `wb = raw_ol.get("window_breakdown")` line and the five deleted kwargs from the `OutlookView(...)` construction. **No bracket read of `window` or `trajectory` survives.**

In `api/app/models/league.py`: delete `StandingRow.strength_score` and `.trajectory_score` (`:66-72`), and drop them from the `roster_rank` comment's cross-reference at `:83`. Leave `window` in place — it still reads off the blob at this commit and becomes the derived value in Task 5.

In `api/app/services/aggregations.py`: delete the `strength_score=` and `trajectory_score=` lines from the `StandingRow(...)` construction (`:802-804`).

- [ ] **Step 10: Fix the test files that die with the model**

1. `tests/test_outlook_build.py` — delete the `roster_value_rank_pct` import and its test (`:26-27`), and the `trajectory_score` assertions (`:66-71`).
2. `tests/test_html_report.py` — the `DynastyOutlook(...)` constructions at `:156` and `:177` lose `window=`/`trajectory=`; add a positive assertion:

```python
def test_report_renders_without_a_window_chip():
    html = _render()          # existing helper
    assert "chip-competing" not in html
    assert "Dynasty Window" not in html
    assert "Trajectory:" not in html
```

3. `api/tests/test_refresh_service.py` — delete the `_backfill_yoy` import (`:7`) and the whole `:73-159` block of tests.
4. `api/tests/services/test_season_ratings_v2.py` — delete the `_backfill_yoy` import (`:12`) and the test that calls it (`:39-65`). If nothing else remains in the file, delete the file.
5. `api/tests/test_owner_view_outlook.py`, `api/tests/test_aggregations.py`, `api/tests/test_capabilities_api.py` — these break here but are **rewritten in Task 5**, where their new assertions belong. For this commit, delete only the assertions on deleted fields so the suite runs; do not add new ones yet.
6. `web/tests/ownerdeepdive/WindowSection.test.tsx`, `web/tests/window.test.ts` — deleted in Task 6, not here. The frontend suite is untouched by Task 3.

- [ ] **Step 11: Run the suites**

```bash
pytest tests/ -q
cd api && pytest tests/ -q && cd ..
```

Both green.

- [ ] **Step 12: Grep clean** (QA gate 2, regression)

```bash
cd "/Users/tomkeefe/Code Apps/public-dynasty"
for s in compute_strength_score compute_trajectory_score strength_inputs \
         trajectory_inputs classify_window _describe_trajectory \
         WindowInput WindowBreakdown window_input_dict _backfill_yoy \
         roster_value_rank_pct; do
  echo "=== $s ==="
  grep -rn --exclude-dir=node_modules --exclude-dir=.next --exclude-dir=.git \
    --exclude-dir=.claude --exclude-dir=docs "\b$s\b" . | grep -v '^CLAUDE.md:'
done
```

Expected: **zero hits in Python.** The only remaining hits are the frontend files Task 6 deletes (`web/lib/types.ts`, `web/lib/window.ts`, `WindowSection.tsx` + its tests, `OwnerDeepDive.test.tsx`) and `StandingsTable.tsx`'s `strength_score`/`trajectory_score`.

- [ ] **Step 13: Run the CLI** (QA gate 2, blocker)

The CLI is the path no web test covers.

```bash
sleeper-dynasty --help
python -c "
from sleeper_dynasty.engine.dynasty import build_dynasty_outlook, DynastyOutlook
import inspect
print(inspect.signature(build_dynasty_outlook))
print([f for f in DynastyOutlook.__dataclass_fields__])
"
```

Expected: signature has six parameters, dataclass has exactly three fields. Then run the real outlook command against the reference league and confirm the HTML report and Docs export complete with **no** `AttributeError` and no chip.

- [ ] **Step 14: Commit**

```bash
git add -A
git commit -m "refactor(engine): retire the Strength x Trajectory window model

build_dynasty_outlook is the only producer of DynastyOutlook, so this
cannot be split: it takes both CLI export paths and six test files with
it. Six dead parameters go with the model rather than being defaulted.

The CLI exports lose the Dynasty Window chip permanently — they have no
Franchise Rating in scope, and a second engine-side derivation would
rebuild the two-models problem this change exists to delete."
```

---

# Task 4: New engine data — league mean ages, held/ideal, and their route into the blob

**Files:**
- Modify: `src/sleeper_dynasty/engine/dynasty.py` (`DraftNeed`, `assess_draft_needs`)
- Modify: `src/sleeper_dynasty/engine/outlook_build.py` (`league_avg_age_by_position`, tuple return, `outlook_to_dict`)
- Modify: `api/app/services/grader.py:1311-1324`
- Modify: `api/app/services/chain_cache.py:125-127` (comment; moved here from Task 3 by the pre-flight ruling)
- Test: `tests/test_dynasty.py`, `tests/test_outlook_build.py`

**Interfaces:**
- Consumes: Task 3's `build_outlooks_by_owner` / `outlook_to_dict`.
- Produces:
  - `DraftNeed(position: str, urgency: str, reason: str, held: int, ideal: int, kind: str)` where `kind ∈ {"starters", "quality", "depth", "aging"}`
  - `league_avg_age_by_position(rosters, players, as_of=None) -> dict[str, float]`
  - `build_outlooks_by_owner(...) -> tuple[dict[str, DynastyOutlook], dict[str, float]]`
  - `outlook_to_dict(outlook, as_of=None, league_avg_age_by_position=None) -> dict` — `age_profile` gains a fifth key, `draft_needs[]` gains three.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_dynasty.py`:

```python
def test_every_need_carries_held_and_ideal_and_its_branch():
    """held/ideal are emitted on EVERY need; `kind` says which branch fired,
    because `urgency` cannot — the depth branch and the aging branch both
    emit "developing"."""
    needs = assess_draft_needs(
        roster_players=_two_rbs_and_a_full_wr_room(),
        position_rankings={}, age_profile=_ap(), total_rosters=12,
    )
    for n in needs:
        assert n.held >= 0 and n.ideal > 0
        assert n.kind in {"starters", "quality", "depth", "aging"}


def test_the_aging_branch_reports_a_full_room():
    """The regression the pips exist to avoid. The aging branch is an `elif`
    reached ONLY when current_count >= ideal_depth, so held >= ideal there —
    four filled pips beside a live need reads as a contradiction, which is why
    the UI gates pips on kind == "depth"."""
    needs = assess_draft_needs(
        roster_players=_full_but_aging_rb_room(),
        position_rankings={}, age_profile=_ap_with_aging_rbs(), total_rosters=12,
    )
    rb = next(n for n in needs if n.position == "RB")
    assert rb.kind == "aging"
    assert rb.held >= rb.ideal


def test_the_depth_branch_reports_a_short_room():
    needs = assess_draft_needs(
        roster_players=_two_rbs_and_a_full_wr_room(),
        position_rankings={}, age_profile=_ap(), total_rosters=12,
    )
    rb = next(n for n in needs if n.position == "RB")
    assert rb.kind == "depth"
    assert rb.held < rb.ideal


def test_no_row_for_a_position_with_no_need():
    """The "QB ()" regression guard. A row with urgency="" can surface as the
    owner's top need in the live LLM packet (franchise_outlook.py ->
    HeroBand.tsx) and would permanently kill the needs empty state."""
    needs = assess_draft_needs(
        roster_players=_a_complete_roster(),
        position_rankings={}, age_profile=_ap_all_young(), total_rosters=12,
    )
    assert needs == []
    assert all(n.urgency for n in needs)
```

Write the four fixture helpers as plain `Player` lists at the top of the file, following the existing `tests/test_dynasty.py` construction idiom. `_IDEAL_DEPTH` is `{"QB": 2, "RB": 4, "WR": 5, "TE": 2}` and `_MIN_STARTERS` is `{"QB": 1, "RB": 2, "WR": 3, "TE": 1}` — size the fixtures against those.

Append to `tests/test_outlook_build.py`:

```python
def test_league_mean_age_is_the_LEAGUE_s_not_one_owner_s():
    """Two owners whose per-position means differ. The league figure must be
    neither owner's own — it is pooled over every rostered player at that
    position, the same way an owner's own avg_age_by_position is pooled over
    theirs. One definition of "mean age at a position", not two."""
    means = league_avg_age_by_position(
        rosters=[_roster(1, ["rb22", "rb24"]), _roster(2, ["rb30"])],
        players=_players({"rb22": ("RB", 22), "rb24": ("RB", 24),
                          "rb30": ("RB", 30)}),
        as_of=date(2026, 1, 1),
    )
    assert means["RB"] == pytest.approx((22 + 24 + 30) / 3)
    assert means["RB"] != 23.0      # owner 1's mean
    assert means["RB"] != 30.0      # owner 2's mean


def test_league_mean_age_skips_k_and_def():
    means = league_avg_age_by_position(
        rosters=[_roster(1, ["k1", "def1", "wr1"])],
        players=_players({"k1": ("K", 30), "def1": ("DEF", 30),
                          "wr1": ("WR", 24)}),
        as_of=date(2026, 1, 1),
    )
    assert set(means) == {"WR"}


def test_build_outlooks_by_owner_returns_the_league_map_alongside():
    outlooks, league_ages = build_outlooks_by_owner(**_kwargs())
    assert isinstance(outlooks, dict) and isinstance(league_ages, dict)


def test_outlook_to_dict_emits_the_league_map_and_the_need_keys():
    outlooks, league_ages = build_outlooks_by_owner(**_kwargs())
    d = outlook_to_dict(
        outlooks["uA"], as_of=date(2026, 1, 1),
        league_avg_age_by_position=league_ages,
    )
    assert d["age_profile"]["league_avg_age_by_position"] == league_ages
    for n in d["draft_needs"]:
        assert {"position", "urgency", "reason", "held", "ideal", "kind"} <= set(n)


def test_outlook_to_dict_without_the_map_emits_an_empty_one():
    """The CLI never computes it. An empty dict is a real reading ("no league
    comparison available"); a missing key would KeyError in owner_view."""
    outlooks, _ = build_outlooks_by_owner(**_kwargs())
    d = outlook_to_dict(outlooks["uA"], as_of=date(2026, 1, 1))
    assert d["age_profile"]["league_avg_age_by_position"] == {}
```

- [ ] **Step 2: Run and verify they fail**

```bash
pytest tests/test_dynasty.py tests/test_outlook_build.py -v
```

Expected: `ImportError` on `league_avg_age_by_position`; `AttributeError: 'DraftNeed' object has no attribute 'held'`.

- [ ] **Step 3: Extend `DraftNeed`**

In `src/sleeper_dynasty/engine/dynasty.py`:

```python
@dataclass
class DraftNeed:
    """A positional need identified from roster and age analysis.

    ``held``/``ideal`` are emitted on EVERY need, but only ``kind == "depth"``
    is a shortfall against ``ideal``, and that is the only row the UI draws
    depth pips on. The starter-quality branch fires at any count, and the
    aging-out branch is an ``elif`` reached only when
    ``current_count >= ideal_depth`` — pips there would draw a FULL room
    beside a live need.

    ``kind`` exists because ``urgency`` cannot carry this: the depth branch and
    the aging branch both emit "developing".
    """

    position: str
    urgency: str  # "immediate" or "developing"
    reason: str
    # Players at this position on the roster, and the roster-construction
    # target for it (`_IDEAL_DEPTH`).
    held: int = 0
    ideal: int = 0
    # "starters" | "quality" | "depth" | "aging" — which branch fired.
    kind: str = ""
```

- [ ] **Step 4: Stamp `kind`/`held`/`ideal` on all four branches**

In `assess_draft_needs`, add the three fields to each of the four `DraftNeed(...)` constructions:

```python
        # Immediate need: below minimum starters.
        if current_count < _MIN_STARTERS.get(pos, 1):
            needs.append(
                DraftNeed(
                    position=pos,
                    urgency="immediate",
                    reason=f"Only {current_count} {pos}(s) on roster, "
                    f"need at least {_MIN_STARTERS[pos]}",
                    held=current_count, ideal=ideal_depth, kind="starters",
                )
            )
            continue
```

```python
            if starters_ranked < _MIN_STARTERS.get(pos, 1):
                needs.append(
                    DraftNeed(
                        position=pos,
                        urgency="immediate",
                        reason=f"No {pos} ranked in starter tier "
                        f"(top {starter_threshold})",
                        held=current_count, ideal=ideal_depth, kind="quality",
                    )
                )
                continue
```

```python
        if current_count < ideal_depth:
            needs.append(
                DraftNeed(
                    position=pos,
                    urgency="developing",
                    reason=f"{current_count}/{ideal_depth} {pos}(s) on roster",
                    held=current_count, ideal=ideal_depth, kind="depth",
                )
            )
        elif aging_at_pos:
            needs.append(
                DraftNeed(
                    position=pos,
                    urgency="developing",
                    reason=f"{len(aging_at_pos)} {pos}(s) aging out "
                    f"({', '.join(p.full_name for p in aging_at_pos)})",
                    held=current_count, ideal=ideal_depth, kind="aging",
                )
            )
```

Do **not** add a row per position — the loop's existing structure already emits only real needs, and that is the `"QB ()"` guard.

- [ ] **Step 5: Add `league_avg_age_by_position`**

In `src/sleeper_dynasty/engine/outlook_build.py`, after `ktc_position_rankings`:

```python
def league_avg_age_by_position(
    rosters: list[Roster],
    players: dict[str, Player],
    as_of: date | None = None,
) -> dict[str, float]:
    """position -> mean age across EVERY rostered player in the league.

    Pooled over players, not averaged over owners' means. That is deliberate:
    an owner's own `AgeProfile.avg_age_by_position` is itself a pooled mean
    over that owner's players, so computing the league figure the same way
    keeps ONE definition of "mean age at a position". A mean-of-owner-means
    would introduce a second averaging step the owner-side figure does not
    have, and a figure that is computed two ways is exactly what this redesign
    exists to delete.

    K and DEF are skipped, matching `dynasty._SKIP_POSITIONS`, so the keys here
    are comparable to an `AgeProfile`'s. A position nobody in the league
    rosters yields no key — the rooms chart plots the OWNER's keys intersected
    with these, so an absent key is simply not drawn.
    """
    from sleeper_dynasty.engine.dynasty import _SKIP_POSITIONS

    ref = as_of or date.today()
    ages: dict[str, list[int]] = {}
    for r in rosters:
        for pid in (r.players or []):
            p = players.get(pid)
            if p is None or p.position in _SKIP_POSITIONS:
                continue
            age = p.age(as_of=ref)
            if age is None:
                continue
            ages.setdefault(p.position, []).append(age)
    return {pos: sum(v) / len(v) for pos, v in ages.items() if v}
```

- [ ] **Step 6: Return the map from `build_outlooks_by_owner`**

Change the signature's return annotation and the final return:

```python
) -> tuple[dict[str, DynastyOutlook], dict[str, float]]:
    """Build a DynastyOutlook per current owner uid, plus the league's own
    per-position mean ages (offseason-safe).

    The league map is returned ALONGSIDE rather than set on each AgeProfile:
    it is league-wide data, and hanging it off a per-roster dataclass would
    duplicate it once per owner and invite the two copies to drift.
    """
```

```python
    return out, league_avg_age_by_position(rosters, players)
```

- [ ] **Step 7: Emit both in `outlook_to_dict`**

```python
def outlook_to_dict(
    outlook: DynastyOutlook,
    as_of: date | None = None,
    league_avg_age_by_position: dict[str, float] | None = None,
) -> dict:
    """JSON-safe serialization (Players -> lite dicts; tuple keys -> strings).

    `league_avg_age_by_position` defaults to `{}` rather than being omitted:
    the CLI path never computes it, and `owner_view` reads the key directly.
    An empty dict is a real reading ("no league comparison available"); a
    missing key would KeyError.
    """
```

In the returned dict, `age_profile` gains a fifth key and `draft_needs` gains three:

```python
        "age_profile": {
            "avg_age_by_position": ap.avg_age_by_position,
            "league_avg_age_by_position": league_avg_age_by_position or {},
            "overall_avg_age": ap.overall_avg_age,
            "aging_risks": [_player_lite(p, ref) for p in ap.aging_risks],
            "core_young": [_player_lite(p, ref) for p in ap.core_young],
        },
```

```python
        "draft_needs": [
            {
                "position": n.position, "urgency": n.urgency, "reason": n.reason,
                "held": n.held, "ideal": n.ideal, "kind": n.kind,
            }
            for n in outlook.draft_needs
        ],
```

- [ ] **Step 8: Wire the grader**

In `api/app/services/grader.py` (~`:1311-1324`):

```python
            outlooks, league_ages = build_outlooks_by_owner(
                rosters=current_rosters, players=players_obj,
                traded_picks=traded_picks, positions=positions,
                ktc_value_by_player=ktc_floats, roster_to_user=r2u_current,
                total_rosters=len(current_rosters),
                num_rounds=num_draft_rounds,
            )
            dynasty_outlooks = {
                uid: outlook_to_dict(ol, league_avg_age_by_position=league_ages)
                for uid, ol in outlooks.items()
            }
```

`dynasty_outlooks` is the as-of-today value layer — always recomputed, never in a `_reuse_prior` copy block — so both new keys land on the first refresh with no `SCHEMA_VERSION` bump. Confirm by grepping `dynasty_outlooks` in `grader.py:1035-1157`: it must appear in **none** of the reuse blocks.

Then update the shape claim in `api/app/services/chain_cache.py:125-127` — the two-`draft_needs` disambiguation comment states the old three-key shape and cites a stale line number:

```python
    # `DraftNeed{position, urgency, reason, held, ideal, kind}` nested inside a
    # roster's `DynastyOutlook` and surfaced via `owner_view.py`'s
```

(Moved here from Task 3 by the pre-flight ruling: the fields it describes only exist as of this task.)

- [ ] **Step 9: Run and verify green**

```bash
pytest tests/ -q
cd api && pytest tests/ -q && cd ..
```

- [ ] **Step 10: Prove the new tests bite**

```bash
export PYTHONPYCACHEPREFIX=/tmp/pycache-outlook
```

| Mutation | Must fail |
|---|---|
| `kind="depth"` → `kind="aging"` on the `current_count < ideal_depth` branch | `test_the_depth_branch_reports_a_short_room` |
| `league_avg_age_by_position` returns the first roster's own means | `test_league_mean_age_is_the_LEAGUE_s_not_one_owner_s` |
| drop the `if p.position in _SKIP_POSITIONS: continue` guard | `test_league_mean_age_skips_k_and_def` |
| `league_avg_age_by_position or {}` → `league_avg_age_by_position` (leaving `None`) | `test_outlook_to_dict_without_the_map_emits_an_empty_one` |
| emit a `DraftNeed(position=pos, urgency="", …)` for every position with no need | `test_no_row_for_a_position_with_no_need` |

Restore after each.

- [ ] **Step 11: Commit**

```bash
git add -A
git commit -m "feat(engine): league per-position mean ages + held/ideal/kind on DraftNeed

Both carry a route into the blob, which rev 2 of the spec omitted:
build_outlooks_by_owner returns the league map alongside the outlooks and
outlook_to_dict emits it. `kind` is the pip discriminator — `urgency`
cannot serve, because the depth branch and the aging branch both emit
\"developing\"."
```

---

# Task 5: API — `OutlookView` reshape, `signal_ranks`, read-time window, redraft gate

**Files:**
- Modify: `api/app/models/leaderboard.py:14-21`
- Modify: `api/app/models/owner.py:90-121` (additive only — the deletions landed in Task 3)
- Modify: `api/app/models/league.py:62-83` (the `window` doc comment only)
- Modify: `api/app/services/franchise_redesign.py` (`live_ratings`)
- Modify: `api/app/services/owner_view.py:186-207` (moves below the rating block)
- Modify: `api/app/services/aggregations.py:794-805`
- Test: `api/tests/test_owner_view_outlook.py`, `api/tests/test_aggregations.py`, `api/tests/test_capabilities_api.py`, `api/tests/services/test_signal_ranks.py` (create), `api/tests/test_chain_cache_outlook_keys.py` (create)

**Interfaces:**
- Consumes: `rating_to_stage` (Task 1), the reshaped blob (Task 4).
- Produces:
  - `PillarBreakdown.signal_ranks: dict[str, int]` (1 = best, ranked by each signal's `raw` descending)
  - `OutlookView(window: str | None, results_z: float | None, assets_z: float | None, tilt: float | None, assets_signal_ranks: dict[str, int], age_profile, draft_capital, draft_needs)`
  - `AgeProfileView.league_avg_age_by_position: dict[str, float]`
  - `DraftNeedView(position, urgency, reason, held: int, ideal: int, kind: str)`
  - `StandingRow.window: str | None` (derived), **no** `strength_score` / `trajectory_score`

- [ ] **Step 1: Write the failing tests**

Create `api/tests/services/test_signal_ranks.py`:

```python
"""signal_ranks reaches the /gm response and the owner page.

PillarBreakdown is rebuilt through `PillarBreakdown(**pd)` in leaderboard.py,
and Pydantic DROPS an extra key — so a rank populated anywhere other than on
the model itself silently never arrives. That is the failure this file exists
to catch.
"""

from app.services.franchise_redesign import live_ratings
from tests.helpers import minimal_chain_cache_entry


def _entry_three_owners():
    return minimal_chain_cache_entry(
        owners={u: {"owner_name": u} for u in ("a", "b", "c")},
        season_records={"2024": {
            u: {"wins": 7, "losses": 6, "ties": 0, "rank": i + 1}
            for i, u in enumerate(("a", "b", "c"))}},
        outcome_signals={
            "a": {"expected_wins": 0.7, "playoff_success": 2.0, "luck": 0.1},
            "b": {"expected_wins": 0.5, "playoff_success": 1.0, "luck": 0.0},
            "c": {"expected_wins": 0.3, "playoff_success": 0.0, "luck": -0.1},
        },
        outlook_signals={
            "a": {"roster_value_share": 0.05, "young_core_share": 0.60,
                  "draft_capital": 100.0},
            "b": {"roster_value_share": 0.11, "young_core_share": 0.20,
                  "draft_capital": 300.0},
            "c": {"roster_value_share": 0.08, "young_core_share": 0.40,
                  "draft_capital": 200.0},
        },
    )


def test_signal_ranks_are_1_is_best_by_raw_descending():
    out = live_ratings(_entry_three_owners())
    assert out["b"]["pillars"]["assets"]["signal_ranks"]["roster_value_share"] == 1
    assert out["c"]["pillars"]["assets"]["signal_ranks"]["roster_value_share"] == 2
    assert out["a"]["pillars"]["assets"]["signal_ranks"]["roster_value_share"] == 3
    # And the ordering is per-signal, not one rank reused across the pillar.
    assert out["a"]["pillars"]["assets"]["signal_ranks"]["young_core_share"] == 1


def test_every_pillar_carries_ranks():
    out = live_ratings(_entry_three_owners())
    for row in out.values():
        for pillar in row["pillars"].values():
            assert set(pillar["signal_ranks"]) == set(pillar["signals"])


def test_signal_ranks_survive_the_pydantic_rebuild():
    """leaderboard.py does `PillarBreakdown(**pd)`; an extra key is dropped."""
    from app.services.leaderboard import build_leaderboard
    board = build_leaderboard(_entry_three_owners(), year="all")
    row = next(r for r in board.rows if r.user_id == "b")
    assert row.pillars["assets"].signal_ranks["roster_value_share"] == 1
```

Rewrite `api/tests/test_owner_view_outlook.py` around the new shape:

```python
def test_window_is_derived_from_the_rating_not_read_off_the_blob():
    """owner_view assembles the outlook block ABOVE where gm_row resolves in
    the original file; if the assignment did not move, `window` is None or a
    NameError. That is the subtle failure the spec itself flags."""
    entry = _entry_with_outlook()
    gm_row = _gm_row(rating=1600)
    detail = build_owner_detail(entry, "uA", gm_row=gm_row, total_owners=12)
    assert detail.outlook.window == "Contending"


def test_a_pre_feature_blob_serves_the_tab_with_the_new_keys_absent():
    """No SCHEMA_VERSION bump, so a blob written before this change still
    carries `window`/`trajectory` and carries NEITHER new key. It must render,
    and its stale keys must reach nothing."""
    entry = _entry_with_pre_feature_outlook()   # has window="Peaking", no held/ideal
    detail = build_owner_detail(entry, "uA", gm_row=_gm_row(rating=1300),
                                total_owners=12)
    assert detail.outlook is not None
    assert detail.outlook.window == "Retooling"        # derived, not "Peaking"
    assert detail.outlook.age_profile.league_avg_age_by_position == {}
    assert all(n.held == 0 and n.ideal == 0 for n in detail.outlook.draft_needs)


def test_an_unrated_owner_has_no_stage():
    """classify_window always returned a label; this deliberately does not."""
    detail = build_owner_detail(_entry_with_outlook(), "uA",
                                gm_row=None, total_owners=12)
    assert detail.outlook.window is None


def test_the_z_receipt_and_the_tilt_carry_the_right_sign():
    gm_row = _gm_row(rating=1600, results_z=0.84, assets_z=1.12)
    detail = build_owner_detail(_entry_with_outlook(), "uA",
                                gm_row=gm_row, total_owners=12)
    assert detail.outlook.results_z == 0.84
    assert detail.outlook.assets_z == 1.12
    assert detail.outlook.tilt == pytest.approx(0.28)


def test_the_retired_fields_are_gone_from_the_response():
    detail = build_owner_detail(_entry_with_outlook(), "uA",
                                gm_row=_gm_row(rating=1600), total_owners=12)
    d = detail.outlook.model_dump()
    for dead in ("window_breakdown", "strength_score",
                 "trajectory_score", "trajectory"):
        assert dead not in d
```

Rewrite `api/tests/test_capabilities_api.py`'s redraft assertion. **Fix the fixture first** — today it has empty `season_records`, so `rated_owners` returns `[]`, `live_ratings` returns `{}`, and the test passes for the wrong reason:

```python
def test_redraft_standings_carry_no_window_even_when_the_league_is_rated():
    """`ratings` is NOT redraft-gated (aggregations.py:725) though
    dynasty_outlooks IS (:755-757). Deriving `window` from the rating ungated
    re-enables the Outlook columns for redraft and labels those franchises
    "Dynasty". The fixture MUST have populated season_records or rated_owners
    returns [] and this proves nothing."""
    entry = _redraft_entry(season_records=_two_completed_seasons())
    resp = build_dashboard(entry, year="all", lens="ktc")
    assert any(r.gm_rating is not None for r in resp.standings)   # league IS rated
    assert all(r.window is None for r in resp.standings)          # and has no stage


def test_dynasty_standings_carry_the_derived_stage():
    entry = _dynasty_entry(season_records=_two_completed_seasons())
    resp = build_dashboard(entry, year="all", lens="ktc")
    rated = [r for r in resp.standings if r.gm_rating is not None]
    assert rated and all(r.window is not None for r in rated)
```

Create `api/tests/test_chain_cache_outlook_keys.py`:

```python
"""The adapted cache pair. No bump and no new persisted computation, so the
standard quartet's "grader stamps it" and "pre-feature default" collapse into
these two."""

from app.services.chain_cache import ChainCache
from tests.helpers import minimal_chain_cache_entry


def test_the_two_new_dynasty_outlook_keys_round_trip(tmp_path):
    entry = minimal_chain_cache_entry(dynasty_outlooks={"uA": {
        "age_profile": {
            "avg_age_by_position": {"RB": 26.5},
            "league_avg_age_by_position": {"RB": 25.9},
            "overall_avg_age": 26.0, "aging_risks": [], "core_young": []},
        "draft_capital": {"picks_by_season": {}, "picks_by_season_round": {},
                          "net_vs_average": 0.0, "status": "neutral"},
        "draft_needs": [{"position": "RB", "urgency": "developing",
                         "reason": "2/4 RB(s) on roster",
                         "held": 2, "ideal": 4, "kind": "depth"}],
    }})
    cache = ChainCache(cache_dir=tmp_path)
    cache.write(entry)
    back = cache.read(entry.league_id)
    ol = back.dynasty_outlooks["uA"]
    assert ol["age_profile"]["league_avg_age_by_position"] == {"RB": 25.9}
    assert ol["draft_needs"][0]["held"] == 2
    assert ol["draft_needs"][0]["kind"] == "depth"


def test_schema_version_is_unchanged():
    """A bump would 409 every league until rebuild for no correctness gain."""
    from app.services.chain_cache import SCHEMA_VERSION
    assert SCHEMA_VERSION == 17
```

- [ ] **Step 2: Run and verify they fail**

```bash
cd api && pytest tests/ -q; cd ..
```

- [ ] **Step 3: Add `signal_ranks` to `PillarBreakdown`**

`api/app/models/leaderboard.py`:

```python
class PillarBreakdown(BaseModel):
    """One pillar's contribution + its per-signal breakdown (full transparency)."""

    weight: float
    z: float
    contribution: int
    signals: dict[str, SignalBreakdown]
    # signal key -> this owner's rank on that signal's RAW value among the
    # rated population, 1 = best (highest raw). Read-time only: written to no
    # ChainCacheEntry field, because persisting it would reopen the schema
    # question the Assets-led Outlook redesign closed by not bumping.
    #
    # It lives HERE rather than being passed alongside because leaderboard.py
    # rebuilds pillars through `PillarBreakdown(**pd)` and Pydantic drops an
    # extra key -- a rank populated anywhere else silently never arrives.
    # This is a public /gm response-shape change.
    signal_ranks: dict[str, int] = {}
```

- [ ] **Step 4: Populate it in `live_ratings`**

In `api/app/services/franchise_redesign.py`, replace the final loop of `live_ratings`:

```python
    for row in out.values():
        row["model"] = model
    _stamp_signal_ranks(out)
    return out


def _stamp_signal_ranks(out: dict[str, dict]) -> None:
    """Rank every owner on every signal's RAW value, 1 = best (highest raw).

    Mutates `out` in place, on the same dicts `compute_gm_ratings` returned, so
    the rank travels with the breakdown it describes and cannot be paired with
    the wrong owner downstream.

    Ties share the lower (better) rank and the next rank is skipped, the way a
    finishing order reads. Read-time only.
    """
    if not out:
        return
    for pillar in next(iter(out.values()))["pillars"]:
        signals = next(iter(out.values()))["pillars"][pillar]["signals"]
        for sig in signals:
            ordered = sorted(
                out,
                key=lambda u: out[u]["pillars"][pillar]["signals"][sig]["raw"],
                reverse=True,
            )
            rank = 0
            prev_raw = None
            for i, uid in enumerate(ordered):
                raw = out[uid]["pillars"][pillar]["signals"][sig]["raw"]
                if raw != prev_raw:
                    rank = i + 1
                    prev_raw = raw
                out[uid]["pillars"][pillar].setdefault("signal_ranks", {})[sig] = rank
```

- [ ] **Step 5: Reshape the owner models**

`api/app/models/owner.py` — **additive only**; `WindowInputView`, `WindowBreakdownView` and `OutlookView`'s five retired fields were deleted in Task 3 (pre-flight ruling). Confirm they are already gone before starting.

- Extend `DraftNeedView`:

```python
class DraftNeedView(BaseModel):
    position: str
    urgency: str
    reason: str
    # Players held at this position and the roster-construction target.
    # Emitted on every need, but only `kind == "depth"` is a shortfall against
    # `ideal` -- the UI draws depth pips on that branch alone, because the
    # aging branch is reached only when held >= ideal and full pips beside a
    # live need reads as a contradiction. 0/0/"" on a pre-feature blob.
    held: int = 0
    ideal: int = 0
    kind: str = ""
```

- Extend `AgeProfileView` with:

```python
    # position -> the LEAGUE's mean age there (pooled over every rostered
    # player, the same way this owner's own avg_age_by_position is pooled).
    # Empty on a pre-feature blob and on the CLI path; the rooms chart then
    # draws no dots rather than inventing a baseline.
    league_avg_age_by_position: dict[str, float] = {}
```

- Replace `OutlookView`:

```python
class OutlookView(BaseModel):
    """The Assets pillar's own page.

    `window` is the competitive-window stage DERIVED from this league's
    Franchise Rating (gm_rating.rating_to_stage), computed at read time and
    persisted nowhere. `str | None`: an unrated owner -- first season, new
    franchise, or a league whose signal stage threw -- has no rating, so has no
    stage, and every surface renders that as an absence captioned by
    `unrated_reason`. The retired `classify_window` always returned a label;
    this deliberately does not.
    """

    window: str | None = None
    # The rating's own two pillar z's, straight off PillarBreakdown.z -- no new
    # derivation. `tilt` is assets_z - results_z: a signed readout of whether
    # the roster is ahead of the trophy case. It is NOT the rung selector; a
    # relation cannot be monotone on an ordered rail.
    results_z: float | None = None
    assets_z: float | None = None
    tilt: float | None = None
    # signal key -> rank among the rated population, 1 = best. Duplicates
    # franchise_rating.pillars["assets"].signal_ranks, which the same response
    # carries; kept here so the Outlook tab reads one object.
    assets_signal_ranks: dict[str, int] = {}
    age_profile: AgeProfileView
    draft_capital: DraftCapitalView
    draft_needs: list[DraftNeedView] = []
```

- [ ] **Step 6: Rebuild the `owner_view` block, below `is_redraft`**

> **Corrected during execution.** This step originally said "below the rating block, because `gm_row` resolves at `:275`". That is false: `gm_row` is a **keyword parameter** of `build_owner_detail` (`:50`), in scope from the function's first line — the spec conflated first *use* with *binding*, and this plan inherited it. Moving the block above the rating block is behaviourally identical and no test can observe it. The real ordering constraint is the **local** `is_redraft` (`:197`); assembling above it raises `UnboundLocalError`. Test that.

In `api/app/services/owner_view.py`:

1. The `WindowBreakdownView` import was dropped in Task 3 — confirm.
2. **Move** the whole `# --- Optional outlook block ---` section (`:186-207`) to sit **after** the `# --- Franchise Rating ---` block (which currently ends ~`:283`) and after `unrated_reason` is computed. Keep the redraft `outlook_view = None` gate with it, and make sure `is_redraft` is still defined before its other users (`roster_rank_view`, `_fr_blurb`) — if the move would leave those without it, hoist the two `is_redraft` lines up on their own and move only the `OutlookView(...)` assembly.
3. Replace the assembly with:

```python
    # --- Optional outlook block (null on pre-feature caches and for redraft).
    #
    # Assembled after `is_redraft` is bound, which is the REAL ordering
    # constraint here -- `gm_row` is a keyword parameter and has been in scope
    # since the first line, so it imposes none. `window` is derived from
    # `gm_row.rating`; there is no second window model to fall back on.
    #
    # `raw_ol["window"]` and `raw_ol["trajectory"]` are NOT read. A pre-feature
    # blob still carries both (no SCHEMA_VERSION bump) and a newly written one
    # carries neither, so a bracket read would KeyError rather than degrade.
    outlook_view: OutlookView | None = None
    raw_ol = None if is_redraft else (entry.dynasty_outlooks or {}).get(user_id)
    if raw_ol:
        ol_sig = (entry.outlook_signals or {}).get(user_id, {})
        ap = raw_ol["age_profile"]
        dc = raw_ol["draft_capital"]
        _results = gm_row.pillars.get("results") if gm_row else None
        _assets = gm_row.pillars.get("assets") if gm_row else None
        outlook_view = OutlookView(
            window=rating_to_stage(gm_row.rating) if gm_row else None,
            results_z=_results.z if _results else None,
            assets_z=_assets.z if _assets else None,
            tilt=(
                round(_assets.z - _results.z, 4)
                if _assets and _results else None
            ),
            assets_signal_ranks=(_assets.signal_ranks if _assets else {}),
            age_profile=AgeProfileView(
                avg_age_by_position=ap["avg_age_by_position"],
                league_avg_age_by_position=ap.get(
                    "league_avg_age_by_position") or {},
                overall_avg_age=ap["overall_avg_age"],
                aging_risks=[PlayerLite(**p) for p in ap["aging_risks"]],
                core_young=[PlayerLite(**p) for p in ap["core_young"]]),
            draft_capital=DraftCapitalView(
                picks_by_season=dc["picks_by_season"],
                picks_by_season_round=dc["picks_by_season_round"],
                net_vs_average=dc["net_vs_average"], status=dc["status"],
                total_value=float(ol_sig.get("draft_capital", 0.0) or 0.0)),
            draft_needs=[DraftNeedView(**n) for n in raw_ol["draft_needs"]])
```

4. Add the import at the top of the file:

```python
from sleeper_dynasty.engine.gm_rating import rating_to_stage
```

`DraftNeedView(**n)` tolerates a pre-feature need dict because all three new fields are defaulted.

- [ ] **Step 7: Standings — derive `window`, gated**

`api/app/models/league.py` — `strength_score`/`trajectory_score` and the `roster_rank` cross-reference were deleted in Task 3. Only the `window` doc comment changes here:

```python
    # The competitive-window stage, DERIVED from `gm_rating` on the same line
    # (gm_rating.py::rating_to_stage) — not a second model. None for an
    # unrated franchise and for a redraft league, which has no Outlook layer
    # at all; the frontend omits the column entirely on that signal rather
    # than ruling it out as a row of em-dashes.
    window: str | None = None
```

`api/app/services/aggregations.py` — the two axis-score lines are already gone (Task 3). Replace the `window` line:

```python
            # Derived from the SAME live_ratings builder the owner page reads,
            # so the stage on /owner/{uid} and the Window here are one string,
            # not two arithmetics that can disagree.
            #
            # Gated on `_outlooks_apply`, NOT on `ratings`: `ratings` is not
            # redraft-gated (:725) though dynasty_outlooks is (:755-757), so an
            # ungated derivation gives every redraft row a non-null window,
            # flips StandingsTable's hasOutlookColumns true, and labels redraft
            # franchises "Dynasty".
            window=(
                rating_to_stage(ratings[uid])
                if _outlooks_apply and uid in ratings else None
            ),
```

Add `from sleeper_dynasty.engine.gm_rating import rating_to_stage` to the imports (`rating_to_letter` is already imported from there).

- [ ] **Step 8: Run and verify green**

```bash
cd api && pytest tests/ -q && cd ..
pytest tests/ -q
```

- [ ] **Step 9: Prove the risky tests bite**

```bash
export PYTHONPYCACHEPREFIX=/tmp/pycache-outlook
```

| Mutation | Must fail |
|---|---|
| drop `_outlooks_apply and` from the `window=` gate in `aggregations.py` | `test_redraft_standings_carry_no_window_even_when_the_league_is_rated` |
| move the `OutlookView(...)` assembly back above the rating block | `test_window_is_derived_from_the_rating_not_read_off_the_blob` (NameError / None) |
| `window=raw_ol.get("window")` instead of `rating_to_stage(...)` | `test_a_pre_feature_blob_serves_the_tab_with_the_new_keys_absent` |
| remove `signal_ranks` from `PillarBreakdown` (leave it only in the dict) | `test_signal_ranks_survive_the_pydantic_rebuild` |
| `tilt=round(_results.z - _assets.z, 4)` (sign flipped) | `test_the_z_receipt_and_the_tilt_carry_the_right_sign` |

Restore after each.

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "feat(api): OutlookView is the Assets pillar; window is derived at read time

- PillarBreakdown gains signal_ranks (public /gm shape change) — it must
  live on the model, because leaderboard.py rebuilds pillars through
  PillarBreakdown(**pd) and Pydantic drops an extra key.
- owner_view assembles the outlook block BELOW the rating block; window
  is rating_to_stage(gm_row.rating), and raw_ol[\"window\"]/[\"trajectory\"]
  are no longer read by bracket access.
- StandingRow.window stays redraft-gated on _outlooks_apply: `ratings` is
  not gated though dynasty_outlooks is, so an ungated derivation would
  label redraft franchises \"Dynasty\"."
```

---

# Task 6: Frontend

All UI work follows the `furniture-styling` skill. `furniture-rules.test.ts` must stay green, and remember it has **no** rule for label collision or axis correctness — green is not evidence the chart is right.

**Files:**
- Modify: `web/lib/types.ts`
- Modify: `web/lib/window.ts`
- Create: `web/components/furniture/StageLadder.tsx`
- Modify: `web/components/RatingBars.tsx` (export `DivergeBar`)
- Create: `web/components/ownerdeepdive/OutlookTab.tsx`
- Rewrite: `web/components/ownerdeepdive/RosterHealthTab.tsx` (exports `RoomsSection`)
- Rewrite: `web/components/ownerdeepdive/FutureDraftTab.tsx` (exports `DraftNeedsSection`, `DraftSection`)
- Delete: `web/components/ownerdeepdive/WindowSection.tsx`, `web/tests/ownerdeepdive/WindowSection.test.tsx`, `web/tests/window.test.ts`
- Modify: `web/components/OwnerDeepDive.tsx:200-249`, `web/components/StandingsTable.tsx` (eight sites), `web/components/methodology/MethodologyContent.tsx`
- Tests: rewrite `web/tests/OwnerDeepDive.test.tsx`, `web/tests/FutureDraftTab.test.tsx`, `web/tests/ownerdeepdive/FutureDraftTab.test.tsx`, `web/tests/ownerdeepdive/RosterHealthTab.test.tsx`, `web/tests/StandingsTable.test.tsx`; create `web/tests/ownerdeepdive/RoomsSection.test.tsx`, `web/tests/ownerdeepdive/OutlookTab.test.tsx`

**Interfaces:**
- Consumes: Task 5's API shape.
- Produces:
  - `WINDOW_STAGES: readonly ["Rebuilding","Retooling","Competing","Contending","Dynasty"]`
  - `<StageLadder stage={string | null} />`
  - `assignLanes(pcts: number[], minSepPct: number): number[]` (exported from `RosterHealthTab.tsx`, pure, unit-tested)
  - `<OutlookTab detail={OwnerDetailResp} />`

## 6a — Types and the stage vocabulary

- [ ] **Step 1: Update `web/lib/types.ts`**

Delete `WindowInput` (`:373-379`) and `WindowBreakdown` (`:381-387`) outright.

Replace `OutlookView` (`:389-397`):

```ts
export interface OutlookView {
  /** Derived from the Franchise Rating (gm_rating.py::rating_to_stage) — not a
   *  second model. Null for an unrated owner: no rating, so no stage. The
   *  retired classify_window always returned a label; this deliberately does
   *  not, and the ladder renders as an absence captioned by unrated_reason. */
  window?: string | null;
  results_z?: number | null;
  assets_z?: number | null;
  /** assets_z − results_z. A signed readout ("the roster is ahead of the
   *  trophy case"), never the rung selector. */
  tilt?: number | null;
  assets_signal_ranks?: Record<string, number>;
  age_profile: AgeProfileView;
  draft_capital: DraftCapitalView;
  draft_needs: DraftNeedView[];
}
```

Extend `DraftNeedView`:

```ts
export interface DraftNeedView {
  position: string;
  urgency: string;
  reason: string;
  /** Depth pips render ONLY when kind === "depth". The aging branch is reached
   *  only when held >= ideal, so pips there would draw a full room beside a
   *  live need. 0/0/"" on a pre-feature blob. */
  held?: number;
  ideal?: number;
  kind?: string;
}
```

Extend `AgeProfileView` with `league_avg_age_by_position?: Record<string, number>;`

Extend `PillarBreakdown` with `signal_ranks?: Record<string, number>;`

In `StandingRow` (`:66-74`), delete `strength_score` and `trajectory_score` and rewrite the comment:

```ts
  /** The three Outlook-derived fields. All null together in a redraft league,
   *  which has no Outlook pillar at all (aggregations.py) — StandingsTable
   *  then omits the Window / Draft cap columns entirely rather than ruling
   *  them out as em-dashes. `window` is DERIVED from `gm_rating` on this same
   *  row (rating_to_stage), so the two can never disagree. Also null for an
   *  unrated franchise. */
  window?: string | null;
  draft_capital_value?: number | null;
```

- [ ] **Step 2: Rewrite `web/lib/window.ts`**

The whole file becomes:

```ts
/** The five competitive-window stages `engine/gm_rating.py::rating_to_stage`
 *  can return, in the fixed order the ladder draws them — low to high.
 *
 *  This is a VALUE CHANGE, not a carry-over: the previous list was the retired
 *  classify_window's five (Rebuilding · Descending · Peaking · Ascending ·
 *  Competing now), which no producer can emit any more. These five match
 *  `.design/components/data/WindowCell.jsx` exactly. */
export const WINDOW_STAGES = [
  "Rebuilding", "Retooling", "Competing", "Contending", "Dynasty",
] as const;

export type WindowStage = (typeof WINDOW_STAGES)[number];
```

Delete `web/tests/window.test.ts` — it tests `WINDOW_THRESHOLDS` and `formatWindowRaw`, both gone.

- [ ] **Step 3: Typecheck**

```bash
cd web && npx tsc --noEmit
```

Expected: errors in `WindowSection.tsx`, `OwnerDeepDive.tsx`, `StandingsTable.tsx` and the test files — every one is fixed below. No errors elsewhere.

## 6b — The stage ladder

- [ ] **Step 4: Write the failing test**

Create `web/tests/furniture/StageLadder.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { StageLadder } from "@/components/furniture/StageLadder";
import { WINDOW_STAGES } from "@/lib/window";

describe("StageLadder", () => {
  it("draws all five rungs in the fixed low-to-high order", () => {
    render(<StageLadder stage="Contending" />);
    const cells = screen.getAllByRole("listitem").map((n) => n.textContent);
    expect(cells).toEqual([...WINDOW_STAGES]);
  });

  it("lights exactly one rung", () => {
    const { container } = render(<StageLadder stage="Contending" />);
    expect(container.querySelectorAll('[data-on="true"]')).toHaveLength(1);
    expect(screen.getByText("Contending").getAttribute("data-on")).toBe("true");
  });

  it("lights none when the owner is unrated", () => {
    const { container } = render(<StageLadder stage={null} />);
    expect(container.querySelectorAll('[data-on="true"]')).toHaveLength(0);
  });

  it("lights none for a stage no producer can emit (a stale blob's word)", () => {
    const { container } = render(<StageLadder stage="Peaking" />);
    expect(container.querySelectorAll('[data-on="true"]')).toHaveLength(0);
  });
});
```

- [ ] **Step 5: Run and verify it fails**

```bash
cd web && npx vitest --config tests/vitest.config.ts run tests/furniture/StageLadder.test.tsx
```

Expected: module not found.

- [ ] **Step 6: Implement**

Create `web/components/furniture/StageLadder.tsx` — a port of `.design/components/data/WindowCell.jsx`, not a redraw:

```tsx
import { WINDOW_STAGES } from "@/lib/window";

/* ---------------------------------------------------------------------------
 * Ported from `.design/components/data/WindowCell.jsx`. WINDOW_STAGES is an
 * ORDERED five-step sequence, low to high — not four quadrants. That file
 * records a scatter plot being tried and abandoned, because it made an ordered
 * position look like a coordinate.
 *
 * Shape is the SegmentControl's: a sunk `--surface-sunk` track, pill radius,
 * and the active rung filled with `--stamp` and reversed out in `--stamp-ink`.
 * Stamp is a ground you reverse type out of, and "the stage you are on" is one
 * of its five sanctioned slots (an active segment).
 * ------------------------------------------------------------------------ */

export function StageLadder({ stage }: { stage?: string | null }) {
  return (
    <ul
      className="flex gap-0.5 rounded-pill bg-surface-sunk p-1"
      aria-label="Competitive window"
    >
      {WINDOW_STAGES.map((s) => {
        const on = s === stage;
        return (
          <li
            key={s}
            data-on={on ? "true" : "false"}
            aria-current={on ? "true" : undefined}
            className={`flex min-h-[30px] flex-1 items-center justify-center whitespace-nowrap rounded-pill px-2 font-mono text-label uppercase tracking-[0.06em] ${
              on ? "bg-stamp font-bold text-stamp-ink" : "text-dim"
            }`}
          >
            {s}
          </li>
        );
      })}
    </ul>
  );
}
```

Check `web/tailwind.config.ts` actually maps `surface-sunk`, `stamp`, `stamp-ink`, `rounded-pill` and `text-label`. If any is missing, **stop and consult `design-system-sync`** — do not invent a literal.

- [ ] **Step 7: Run and verify green**

```bash
npx vitest --config tests/vitest.config.ts run tests/furniture/StageLadder.test.tsx
```

- [ ] **Step 8: Commit**

```bash
cd .. && git add web/lib/types.ts web/lib/window.ts \
  web/components/furniture/StageLadder.tsx \
  web/tests/furniture/StageLadder.test.tsx
git rm web/tests/window.test.ts
git commit -m "feat(web): stage ladder + the new five-stage vocabulary"
```

## 6c — The rooms chart (§4)

- [ ] **Step 9: Write the failing tests**

Create `web/tests/ownerdeepdive/RoomsSection.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { RoomsSection, assignLanes } from "@/components/ownerdeepdive/RosterHealthTab";
import type { OutlookView } from "@/lib/types";

function outlook(
  own: Record<string, number>, league: Record<string, number>,
): OutlookView {
  return {
    window: "Contending",
    age_profile: {
      avg_age_by_position: own,
      league_avg_age_by_position: league,
      overall_avg_age: 26,
      aging_risks: [],
      core_young: [],
    },
    draft_capital: {
      picks_by_season: {}, picks_by_season_round: {},
      net_vs_average: 0, status: "neutral", total_value: 0,
    },
    draft_needs: [],
  } as unknown as OutlookView;
}

describe("assignLanes", () => {
  it("puts two labels closer than the separation onto different lanes", () => {
    // Two rooms 0.1 years apart on a ±2yr axis = 2.5 percentage points.
    expect(assignLanes([48.75, 51.25], 11)).toEqual([0, 1]);
  });

  it("keeps well-separated labels on one lane", () => {
    expect(assignLanes([10, 40, 70, 95], 11)).toEqual([0, 0, 0, 0]);
  });

  it("opens a third lane when two are already occupied nearby", () => {
    expect(assignLanes([50, 51, 52], 11)).toEqual([0, 1, 2]);
  });

  it("reuses lane 0 once the gap reopens", () => {
    expect(assignLanes([50, 51, 70], 11)).toEqual([0, 1, 0]);
  });

  it("returns an empty array for no dots", () => {
    expect(assignLanes([], 11)).toEqual([]);
  });
});

describe("RoomsSection", () => {
  it("plots the OWNER's positions, not a fixed four", () => {
    render(<RoomsSection outlook={outlook(
      { QB: 26, RB: 26.5, WR: 24.5, TE: 27, FB: 29 },
      { QB: 26.8, RB: 25.9, WR: 25.6, TE: 27.4, FB: 28.2 },
    )} />);
    for (const p of ["QB", "RB", "WR", "TE", "FB"]) {
      expect(screen.getByText(p, { exact: false })).toBeTruthy();
    }
  });

  it("does not draw a league key the owner holds none of", () => {
    render(<RoomsSection outlook={outlook(
      { QB: 26 }, { QB: 26.8, RB: 25.9 },
    )} />);
    expect(screen.queryByText(/^RB/)).toBeNull();
  });

  it("renders nothing to compare against when the league map is empty", () => {
    // A pre-feature blob. Absence, not a chart against zero.
    render(<RoomsSection outlook={outlook({ QB: 26 }, {})} />);
    expect(screen.getByText(/league comparison/i)).toBeTruthy();
  });

  it("reads younger as positive from the SIGN of the gap, not absolute age", () => {
    // A 27.0 TE room is young; a 27.0 RB room is old. Both are 27.0.
    const { container } = render(<RoomsSection outlook={outlook(
      { TE: 27.0, RB: 27.0 }, { TE: 27.6, RB: 26.0 },
    )} />);
    const te = container.querySelector('[data-room="TE"] [data-gap]');
    const rb = container.querySelector('[data-room="RB"] [data-gap]');
    expect(te?.className).toContain("text-pos-strong");
    expect(rb?.className).toContain("text-neg-strong");
  });

  it("shows the raw age beneath each dot", () => {
    render(<RoomsSection outlook={outlook({ RB: 26.5 }, { RB: 25.9 })} />);
    expect(screen.getByText("26.5 yr")).toBeTruthy();
  });
});
```

- [ ] **Step 10: Run and verify they fail**

```bash
cd web && npx vitest --config tests/vitest.config.ts run tests/ownerdeepdive/RoomsSection.test.tsx
```

- [ ] **Step 11: Rewrite `RosterHealthTab.tsx`**

Replace the whole file:

```tsx
"use client";

import { OutlookView, PlayerLite } from "@/lib/types";
import { Panel } from "../furniture/Panel";
import { Row } from "../furniture/Row";
import { SectionHeader, useSectionCollapse } from "../furniture/SectionCollapse";
import { Card, CardHead } from "./ui";

/* ---------------------------------------------------------------------------
 * §4 "Your rooms vs the league" — a dot plot on a RELATIVE axis, zero = that
 * position's league average.
 *
 * An absolute age axis cannot carry a verdict: a 27.0 TE room is young and a
 * 27.0 RB room is old, so every dot would need a different reference. The
 * absolute version with unlabelled league-average ticks was built and
 * rejected — the ticks could not be attributed to their dots. Left of centre
 * IS the verdict here; raw age rides beneath each dot.
 * ------------------------------------------------------------------------ */

/** Half-width of the axis in years. Beyond it a dot clamps to the edge; the
 *  label still states the true gap. */
const AXIS_YEARS = 2;

/** Minimum horizontal separation between two labels in the same lane, as
 *  percentage points of the track. A label is roughly 56px in a ~500px track,
 *  so ~11 points. Percentage rather than pixels so the walk is
 *  resolution-independent and unit-testable. */
const MIN_SEP_PCT = 11;

/** Vertical step per collision lane. */
const LANE_STEP_PX = 18;
const STEM_BASE_PX = 12;

/**
 * Assign each dot (given as its position along the track, 0-100) to the
 * lowest lane whose last-placed label is at least `minSepPct` away.
 *
 * Label collision here is real, not cosmetic: rooms collide whenever two sit
 * within ~0.3 years, and hand-placing passes on one league's data and breaks
 * on the next. Lanes grow as needed rather than capping at two — three rooms
 * inside one label width is an ordinary roster, not a pathological one.
 *
 * `pcts` need not be sorted; lanes are assigned in left-to-right order and
 * returned in the caller's original order.
 */
export function assignLanes(pcts: number[], minSepPct: number): number[] {
  const order = pcts.map((p, i) => ({ p, i })).sort((a, b) => a.p - b.p);
  const lastInLane: number[] = [];
  const lanes = new Array<number>(pcts.length);
  for (const { p, i } of order) {
    let lane = 0;
    while (lane < lastInLane.length && p - lastInLane[lane] < minSepPct) lane += 1;
    lastInLane[lane] = p;
    lanes[i] = lane;
  }
  return lanes;
}

/** Younger reads as positive, from the SIGN of the gap alone.
 *
 *  This is a NEW helper on purpose. The old `ageTextTone` thresholded on
 *  ABSOLUTE age (>=27 negative, <=24.5 positive), which is exactly what a
 *  relative axis exists to replace. The stance is not universally true — a
 *  room can be too young to produce now — and that is accepted: the sign alone
 *  is the alternative.
 *
 *  Tone lands on the FIGURE, never on the dot. Colour never carries
 *  information that is not also in the figure. */
function gapTone(gap: number): string {
  if (gap < 0) return "text-pos-strong";
  if (gap > 0) return "text-neg-strong";
  return "text-dim";
}

function fmtGap(gap: number): string {
  return `${gap > 0 ? "+" : gap < 0 ? "−" : "±"}${Math.abs(gap).toFixed(1)}`;
}

export function RoomsSection({ outlook }: { outlook: OutlookView }) {
  const ap = outlook.age_profile;
  const league = ap.league_avg_age_by_position ?? {};
  // `SectionCollapse` exports a HOOK plus a `SectionHeader`, not a wrapper
  // component — same shape TradeProductionCard.tsx and TradeScoreboard.tsx use.
  const roster = useSectionCollapse("outlook-roster");

  // The owner's OWN keys, intersected with the league map. The position set is
  // not fixed at four: an FB yields a fifth key, and a position the owner
  // holds none of yields no key at all (dynasty.py builds
  // avg_age_by_position from whatever non-K/DEF positions the roster carries).
  // A league key with no owner dot is simply not drawn.
  const rooms = Object.entries(ap.avg_age_by_position)
    .filter(([pos]) => league[pos] != null)
    .map(([pos, age]) => ({ pos, age, gap: age - league[pos] }))
    .sort((a, b) => a.gap - b.gap);

  if (rooms.length === 0) {
    return (
      <Card>
        <CardHead title="Your rooms vs the league" />
        <p className="text-figure leading-snug text-dim">
          A league comparison lands here on the next refresh.
        </p>
      </Card>
    );
  }

  const pcts = rooms.map(
    (r) => 50 + (Math.max(-AXIS_YEARS, Math.min(AXIS_YEARS, r.gap)) / AXIS_YEARS) * 50,
  );
  const lanes = assignLanes(pcts, MIN_SEP_PCT);
  const laneCount = Math.max(...lanes) + 1;

  return (
    <Card>
      <CardHead
        title="Your rooms vs the league"
        right={
          <span className="font-mono text-label uppercase tracking-[0.11em] text-dim">
            years younger ← · → years older
          </span>
        }
      />
      <Panel>
        <div
          className="relative px-3.5 py-5"
          style={{ minHeight: 76 + laneCount * LANE_STEP_PX }}
        >
          {/* The axis: a --rule hairline with a --rule-strong zero line. */}
          <div className="absolute inset-x-3.5 top-5 h-px bg-rule" />
          <div className="absolute top-3 h-[18px] w-px bg-rule-strong" style={{ left: "50%" }} />
          {[-2, -1, 1, 2].map((t) => (
            <div
              key={t}
              className="absolute top-4 h-[7px] w-px bg-rule"
              style={{ left: `${50 + (t / AXIS_YEARS) * 50}%` }}
            />
          ))}
          {rooms.map((r, i) => (
            <div
              key={r.pos}
              data-room={r.pos}
              className="absolute -translate-x-1/2"
              style={{ left: `${pcts[i]}%`, top: 12 }}
            >
              <span className="mx-auto block h-[7px] w-[7px] rounded-pill bg-ink" />
              <span
                className="mx-auto block w-px bg-rule"
                style={{ height: STEM_BASE_PX + lanes[i] * LANE_STEP_PX }}
              />
              <span className="block whitespace-nowrap text-center font-mono text-label uppercase tracking-[0.11em] text-dim">
                {r.pos}{" "}
                <span data-gap className={`tabular ${gapTone(r.gap)}`}>{fmtGap(r.gap)}</span>
              </span>
              <span className="block whitespace-nowrap text-center font-mono text-label tabular text-dim">
                {r.age.toFixed(1)} yr
              </span>
            </div>
          ))}
        </div>
      </Panel>
      <p className="mt-2 max-w-[68ch] text-figure leading-snug text-dim">
        Zero is that position&rsquo;s league average, so left of centre is a younger room
        than the league&rsquo;s. Raw age sits beneath each dot.
      </p>

      <SectionHeader
        title="Young core and aging risks"
        note={`${ap.core_young.length} young · ${ap.aging_risks.length} aging`}
        open={roster.open}
        onToggle={roster.toggle}
      />
      {roster.open && (
        <div className="mt-2 grid grid-cols-1 gap-x-6 sm:grid-cols-2">
          <PlayerLedger players={[...ap.core_young].sort((a, b) => (a.age ?? 99) - (b.age ?? 99))} />
          <PlayerLedger players={[...ap.aging_risks].sort((a, b) => (b.age ?? 0) - (a.age ?? 0))} />
        </div>
      )}
    </Card>
  );
}

function PlayerLedger({ players }: { players: PlayerLite[] }) {
  if (players.length === 0) {
    return (
      <div className="font-mono text-label uppercase tracking-[0.11em] text-dim">
        None on record
      </div>
    );
  }
  return (
    <Panel>
      {players.map((p) => (
        <Row key={p.player_id} className="grid-cols-[minmax(0,1fr)_34px_34px] items-center gap-2">
          <span className="min-w-0 truncate font-display text-figure font-bold tracking-[-0.02em]">
            {p.full_name}
          </span>
          <span className="font-mono text-label uppercase tracking-[0.11em] text-dim">{p.position}</span>
          <span className="text-right font-mono text-figure tabular text-dim">
            {p.age != null ? p.age : "—"}
          </span>
        </Row>
      ))}
    </Panel>
  );
}
```

Both `overall_avg_age` strips and the four-rail chart are gone, as is `ageTextTone`.

Read `web/components/furniture/SectionCollapse.tsx` before wiring it and match its actual prop names.

- [ ] **Step 12: Run and verify green**

```bash
npx vitest --config tests/vitest.config.ts run tests/ownerdeepdive/RoomsSection.test.tsx
```

Delete `web/tests/ownerdeepdive/RosterHealthTab.test.tsx` — `RoomsSection.test.tsx` replaces it.

- [ ] **Step 13: Prove the collision walk bites**

Change `while (lane < lastInLane.length && p - lastInLane[lane] < minSepPct)` to `if (false)` — `"puts two labels closer than the separation onto different lanes"` and `"opens a third lane"` must both fail. Restore.

## 6d — Needs (§3) and Draft (§5)

> **CORRECTED during execution — the code below shipped with a Critical layout bug and was fixed in a follow-up round.** The needs ledger's head row hid three of four columns below 701px while its **body row hid only one**, leaving three in-flow children against a two-column template. CSS Grid row-major placement then wrapped `reason` — the row's whole payload — into the 34px first column. jsdom does not lay out grid, so **no test caught it and none could**. Two rules were broken at once: `Row`'s column contract (the template must be repeated verbatim on head and body, and the *effective* column count is part of that) and Furniture rule 5 (on mobile an entry becomes a **card**, not a squeezed row). The narrow rendering of both ledgers in this file must use `CardList`/`EntryCard`, matching `StandingsTable.tsx`, `TradeStatTable.tsx`, `TradeScoreboard.tsx` and `Leaderboard.tsx`. Do not copy the `hidden min-[701px]:*` pattern below into a new ledger.

- [ ] **Step 14: Write the failing tests**

Rewrite `web/tests/ownerdeepdive/FutureDraftTab.test.tsx` (and delete the duplicate `web/tests/FutureDraftTab.test.tsx` — there are two files by that name and they test the same component):

```tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { DraftNeedsSection, DraftSection } from "@/components/ownerdeepdive/FutureDraftTab";
import type { OutlookView, DraftSkillView } from "@/lib/types";

const BASE = {
  window: "Contending",
  age_profile: {
    avg_age_by_position: {}, league_avg_age_by_position: {},
    overall_avg_age: 26, aging_risks: [], core_young: [],
  },
  draft_capital: {
    picks_by_season: { "2026": 2, "2027": 3 },
    picks_by_season_round: { "2026-2": 1, "2026-3": 1, "2027-1": 1, "2027-2": 1, "2027-4": 1 },
    net_vs_average: 1.8, status: "pick-rich", total_value: 4200,
  },
  draft_needs: [],
} as unknown as OutlookView;

function withNeeds(needs: OutlookView["draft_needs"]): OutlookView {
  return { ...BASE, draft_needs: needs };
}

describe("DraftNeedsSection", () => {
  it("draws depth pips only on the depth branch", () => {
    const { container } = render(<DraftNeedsSection outlook={withNeeds([
      { position: "RB", urgency: "developing", reason: "2/4 RB(s) on roster",
        held: 2, ideal: 4, kind: "depth" },
    ])} />);
    const pips = container.querySelectorAll('[data-pip]');
    expect(pips).toHaveLength(4);
    expect(container.querySelectorAll('[data-pip="filled"]')).toHaveLength(2);
  });

  it("draws NO pips on a full room flagged for aging", () => {
    // The contradiction the gate exists to prevent: four filled pips beside a
    // live need. The aging branch is an elif reached only when held >= ideal.
    const { container } = render(<DraftNeedsSection outlook={withNeeds([
      { position: "TE", urgency: "developing", reason: "1 TE(s) aging out (Kelce)",
        held: 2, ideal: 2, kind: "aging" },
    ])} />);
    expect(container.querySelectorAll("[data-pip]")).toHaveLength(0);
    expect(screen.getByText(/aging out/)).toBeTruthy();
  });

  it("draws no pips on the starter-quality branch either", () => {
    const { container } = render(<DraftNeedsSection outlook={withNeeds([
      { position: "WR", urgency: "immediate", reason: "No WR ranked in starter tier (top 36)",
        held: 5, ideal: 5, kind: "quality" },
    ])} />);
    expect(container.querySelectorAll("[data-pip]")).toHaveLength(0);
  });

  it("renders position codes in the mono face", () => {
    // Bricolage's Q carries a long baseline tail, so QB in the display face
    // reads as underlined at label sizes.
    render(<DraftNeedsSection outlook={withNeeds([
      { position: "QB", urgency: "immediate", reason: "Only 0 QB(s) on roster, need at least 1",
        held: 0, ideal: 2, kind: "starters" },
    ])} />);
    expect(screen.getByText("QB").className).toContain("font-mono");
  });

  it("says what will appear here when there are no needs", () => {
    render(<DraftNeedsSection outlook={withNeeds([])} />);
    expect(screen.getByText(/no pressing needs/i)).toBeTruthy();
  });

  it("tolerates a pre-feature need with no held/ideal/kind", () => {
    const { container } = render(<DraftNeedsSection outlook={withNeeds([
      { position: "RB", urgency: "developing", reason: "2/4 RB(s) on roster" } as never,
    ])} />);
    expect(container.querySelectorAll("[data-pip]")).toHaveLength(0);
    expect(screen.getByText(/2\/4/)).toBeTruthy();
  });
});

describe("DraftSection", () => {
  const skill: DraftSkillView = { score: 0.4, rank: 4, of: 12 };

  it("puts the skill ordinal on the section header, not in a hero card", () => {
    render(<DraftSection outlook={BASE} draftSkill={skill} />);
    const head = screen.getByText(/skill #4 \/ 12/i);
    expect(head).toBeTruthy();
    expect(screen.queryByText(/^Draft skill$/)).toBeNull();
  });

  it("lists every season's picks and rounds, and totals them", () => {
    render(<DraftSection outlook={BASE} draftSkill={skill} />);
    expect(screen.getByText("2026")).toBeTruthy();
    expect(screen.getByText("2027")).toBeTruthy();
    expect(screen.getByText("5")).toBeTruthy();   // total row
  });

  it("omits the skill meta entirely when there is no score", () => {
    render(<DraftSection outlook={BASE} draftSkill={null} />);
    expect(screen.queryByText(/skill #/i)).toBeNull();
  });
});
```

- [ ] **Step 15: Run and verify they fail**

```bash
npx vitest --config tests/vitest.config.ts run tests/ownerdeepdive/FutureDraftTab.test.tsx
```

- [ ] **Step 16: Rewrite `FutureDraftTab.tsx`**

Replace the whole file:

```tsx
"use client";

import { DraftSkillView, DraftNeedView, OutlookView } from "@/lib/types";
import { Panel } from "../furniture/Panel";
import { Row } from "../furniture/Row";
import { Card, CardHead } from "./ui";
import { ordinal } from "./util";

const URGENCY_TONE: Record<string, string> = {
  immediate: "text-neg-strong",
  developing: "text-dim",
};

/* ---------------------------------------------------------------------------
 * §3 Draft needs and §5 Draft — two sections out of one file, because they are
 * two readings of the same draft_capital / draft_needs pair and change
 * together. §4 (the rooms chart) sits between them on the page.
 * ------------------------------------------------------------------------ */

/** Depth as filled/hollow pips — ONLY on the depth-shortfall branch.
 *
 *  `assess_draft_needs` has four branches and only `kind === "depth"` is a
 *  shortfall against `ideal`. The starter-quality branch fires at any count,
 *  and the aging branch is an `elif` reached only when held >= ideal — pips
 *  there would draw a FULL room beside a live need, which reads as a
 *  contradiction. Those rows show their reason with no depth graphic. */
function DepthPips({ held, ideal }: { held: number; ideal: number }) {
  return (
    <span className="flex items-center gap-[3px]" aria-label={`${held} of ${ideal}`}>
      {Array.from({ length: ideal }, (_, i) => (
        <span
          key={i}
          data-pip={i < held ? "filled" : "hollow"}
          className={`h-[7px] w-[7px] rounded-pill ${
            i < held ? "bg-ink" : "border border-rule-strong"
          }`}
        />
      ))}
    </span>
  );
}

function showsPips(n: DraftNeedView): boolean {
  return n.kind === "depth" && (n.ideal ?? 0) > 0;
}

export function DraftNeedsSection({ outlook }: { outlook: OutlookView }) {
  const needs = outlook.draft_needs;
  return (
    <Card>
      <CardHead
        title="Draft needs"
        right={
          <span className="font-mono text-label uppercase tracking-[0.11em] text-dim">
            filled · hollow = depth you hold vs depth you want
          </span>
        }
      />
      {needs.length === 0 ? (
        <p className="text-figure leading-snug text-dim">
          No pressing needs. A hole shows up here as soon as a room thins out.
        </p>
      ) : (
        <Panel>
          <Row
            variant="head"
            className="grid-cols-[34px_minmax(0,1fr)] gap-2 min-[701px]:grid-cols-[34px_58px_78px_minmax(0,1fr)]"
          >
            <div>Room</div>
            <div className="hidden min-[701px]:block">Depth</div>
            <div className="hidden min-[701px]:block">Urgency</div>
            <div className="hidden min-[701px]:block">Why</div>
          </Row>
          {needs.map((n, i) => (
            <Row
              key={`${n.position}-${i}`}
              className="grid-cols-[34px_minmax(0,1fr)] items-center gap-2 min-[701px]:grid-cols-[34px_58px_78px_minmax(0,1fr)]"
            >
              {/* Mono, not the display face: Bricolage's Q carries a long
                  baseline tail, so QB reads as underlined at label sizes. */}
              <span className="font-mono text-figure font-semibold uppercase tracking-[0.06em] text-ink">
                {n.position}
              </span>
              <span className="hidden min-[701px]:flex items-center">
                {showsPips(n) ? (
                  <DepthPips held={n.held ?? 0} ideal={n.ideal ?? 0} />
                ) : (
                  <span className="font-mono text-label text-dim">—</span>
                )}
              </span>
              <span
                className={`font-mono text-label uppercase tracking-[0.11em] ${
                  URGENCY_TONE[n.urgency] ?? "text-dim"
                }`}
              >
                {n.urgency}
              </span>
              <span className="min-w-0 truncate text-figure text-body" title={n.reason}>
                {n.reason}
              </span>
            </Row>
          ))}
        </Panel>
      )}
    </Card>
  );
}

function roundsForSeason(
  byRound: Record<string, number>, season: string,
): { round: number; count: number }[] {
  const out: { round: number; count: number }[] = [];
  for (const [k, c] of Object.entries(byRound)) {
    const [s, r] = k.split("-");
    if (s === season) out.push({ round: Number(r), count: c });
  }
  return out.sort((a, b) => a.round - b.round);
}

export function DraftSection({
  outlook, draftSkill,
}: {
  outlook: OutlookView;
  draftSkill?: DraftSkillView | null;
}) {
  const dc = outlook.draft_capital;
  const seasons = Object.keys(dc.picks_by_season).sort();
  const total = Object.values(dc.picks_by_season).reduce((a, b) => a + b, 0);

  /* The skill ordinal is a META LINE on the section header, not a hero card.
     One ordinal does not carry a hero, and it was the loudest thing on a tab
     whose subject is the roster. */
  const meta = [
    draftSkill ? `skill #${draftSkill.rank} / ${draftSkill.of}` : null,
    `${total} future pick${total === 1 ? "" : "s"}`,
    seasons[0] ? `next class ${seasons[0]}` : null,
  ].filter(Boolean).join(" · ");

  return (
    <Card>
      <CardHead
        title="Draft"
        right={
          <span className="font-mono text-label uppercase tracking-[0.11em] text-dim">
            {meta}
          </span>
        }
      />
      {seasons.length === 0 ? (
        <p className="text-figure leading-snug text-dim">
          Future picks show up here as soon as this franchise holds one.
        </p>
      ) : (
        <Panel>
          <Row variant="head" className="grid-cols-[54px_40px_minmax(0,1fr)] gap-2">
            <div>Season</div>
            <div className="text-right">Picks</div>
            <div className="pl-3">Rounds</div>
          </Row>
          {seasons.map((s) => {
            const rounds = roundsForSeason(dc.picks_by_season_round, s);
            return (
              <Row key={s} className="grid-cols-[54px_40px_minmax(0,1fr)] items-center gap-2">
                <div className="font-mono text-figure tabular text-dim">{s}</div>
                <div className="text-right font-mono text-figure font-semibold tabular">
                  {dc.picks_by_season[s]}
                </div>
                <div className="min-w-0 truncate pl-3 font-mono text-figure tracking-[0.06em] text-dim">
                  {rounds.length === 0
                    ? "—"
                    : rounds
                        .map((r) => `${ordinal(r.round)}${r.count > 1 ? ` ×${r.count}` : ""}`)
                        .join("  ·  ")}
                </div>
              </Row>
            );
          })}
          {/* Totals the VISIBLE rows, and names what it totals. */}
          <Row variant="total" className="grid-cols-[54px_40px_minmax(0,1fr)] items-center gap-2">
            <div className="font-display text-name font-bold tracking-[-0.024em]">Total</div>
            <div className="text-right font-mono text-figure font-semibold tabular">{total}</div>
            <div className="min-w-0 truncate pl-3 font-mono text-label text-dim">
              {dc.net_vs_average >= 0
                ? `${dc.net_vs_average.toFixed(1)} above league average`
                : `${Math.abs(dc.net_vs_average).toFixed(1)} below league average`}
            </div>
          </Row>
        </Panel>
      )}
    </Card>
  );
}
```

- [ ] **Step 17: Run and verify green**

```bash
npx vitest --config tests/vitest.config.ts run tests/ownerdeepdive/FutureDraftTab.test.tsx
```

- [ ] **Step 18: Prove the pip gate bites**

Change `showsPips` to `return (n.ideal ?? 0) > 0;` — `"draws NO pips on a full room flagged for aging"` and `"draws no pips on the starter-quality branch either"` must both fail. Restore.

## 6e — The tab host: Hero (§1) + Assets ledger (§2)

> **CORRECTED during execution — the `AssetsLedger` code below carried the SAME defect as §6d's needs ledger, and I wrote it twice.** Its body row hid one cell below 701px while the head hid two, leaving four in-flow children against a three-track template — CSS Grid then wraps the overflow into the first column. jsdom lays out no grid, so no test can catch this class of bug. **The rule, stated once for every ledger in this plan:** a `Row`'s in-flow child count must equal its column-template count at *every* breakpoint, and the narrow rendering must be a real `CardList`/`EntryCard` tree rather than a squeezed grid (Furniture rule 5). The shipped version uses a desktop-only grid inside `hidden min-[701px]:block` with **no** responsive variant and **no** hidden cell, plus a card stack beneath — counts measured in the rendered DOM, not read off source.

- [ ] **Step 19: Export `DivergeBar`**

`ContributionRow` is a fixed three-column grid (`168px_1fr_52px`); the Assets ledger is five columns, so the row is not reusable — but the bar is. In `web/components/RatingBars.tsx`, change `function DivergeBar` to `export function DivergeBar` and add:

```tsx
/** Exported so a ledger with a different column contract (the Outlook tab's
 *  five-column Assets ledger) can draw the SAME bar without inheriting
 *  ContributionRow's three-track grid. The bar is the grammar; the grid is
 *  the sentence. */
```

- [ ] **Step 20: Write the failing tests**

Create `web/tests/ownerdeepdive/OutlookTab.test.tsx`:

```tsx
import { render, screen, within } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { OutlookTab } from "@/components/ownerdeepdive/OutlookTab";
import type { OwnerDetailResp } from "@/lib/types";

function detail(over: Record<string, unknown> = {}): OwnerDetailResp {
  return {
    user_id: "uA",
    owner: { user_id: "uA", owner_name: "Tom" },
    unrated_reason: null,
    roster_rank: { rank: 3, of: 12 },
    draft_skill: { score: 0.4, rank: 4, of: 12 },
    franchise_rating: {
      letter: "A-", rating: 1688, rank: 2, of: 12, trend: 1,
      pillar_highlights: {},
      pillars: {
        results: { weight: 0.6, z: 0.84, contribution: 138, signals: {}, signal_ranks: {} },
        assets: {
          weight: 0.4, z: 1.12, contribution: 75,
          signals: {
            roster_value_share: { raw: 0.098, z: 1.4, weight: 0.45, contribution: 41 },
            young_core_share: { raw: 0.41, z: 1.8, weight: 0.35, contribution: 52 },
            draft_capital: { raw: 4200, z: -0.9, weight: 0.20, contribution: -18 },
          },
          signal_ranks: { roster_value_share: 3, young_core_share: 2, draft_capital: 10 },
        },
      },
    },
    outlook: {
      window: "Contending",
      results_z: 0.84, assets_z: 1.12, tilt: 0.28,
      assets_signal_ranks: { roster_value_share: 3, young_core_share: 2, draft_capital: 10 },
      age_profile: {
        avg_age_by_position: { RB: 26.5 },
        league_avg_age_by_position: { RB: 25.9 },
        overall_avg_age: 26, aging_risks: [], core_young: [],
      },
      draft_capital: {
        picks_by_season: { "2026": 2, "2027": 3 },
        picks_by_season_round: { "2026-2": 1, "2026-3": 1, "2027-1": 1, "2027-2": 1, "2027-4": 1 },
        net_vs_average: -1.8, status: "pick-poor", total_value: 4200,
      },
      draft_needs: [],
    },
    ...over,
  } as unknown as OwnerDetailResp;
}

describe("OutlookTab hero", () => {
  it("names the pillar, its weight and the grade in the kicker", () => {
    render(<OutlookTab detail={detail()} />);
    expect(screen.getByText(/Assets — 40% of your A−/)).toBeTruthy();
  });

  it("states the pillar's point contribution in the verdict line", () => {
    render(<OutlookTab detail={detail()} />);
    expect(screen.getByText(/\+75 rating points/)).toBeTruthy();
  });

  it("lights the derived stage on the ladder and nothing else", () => {
    const { container } = render(<OutlookTab detail={detail()} />);
    expect(container.querySelectorAll('[data-on="true"]')).toHaveLength(1);
    expect(screen.getByText("Contending").getAttribute("data-on")).toBe("true");
  });

  it("shows both z's and the tilt as the receipt", () => {
    render(<OutlookTab detail={detail()} />);
    expect(screen.getByText(/Results z \+0\.84/)).toBeTruthy();
    expect(screen.getByText(/Assets z \+1\.12/)).toBeTruthy();
  });

  it("renders an absence, not a fallback label, for an unrated owner", () => {
    const { container } = render(<OutlookTab detail={detail({
      franchise_rating: null,
      unrated_reason: "first_season",
      outlook: { ...(detail().outlook as object), window: null } as never,
    })} />);
    expect(container.querySelectorAll('[data-on="true"]')).toHaveLength(0);
    expect(screen.getByText(/first season/i)).toBeTruthy();
  });
});

describe("OutlookTab assets ledger", () => {
  it("gives Figure and Rank separate headed columns", () => {
    render(<OutlookTab detail={detail()} />);
    const head = screen.getByTestId("assets-ledger-head");
    expect(within(head).getByText("Figure")).toBeTruthy();
    expect(within(head).getByText("Rank")).toBeTruthy();
    // NOT the combined "9.8% · 3rd" run-on that was built and rejected.
    expect(screen.queryByText("9.8% · 3rd")).toBeNull();
  });

  it("reconciles: the visible rows sum to the total shown", () => {
    render(<OutlookTab detail={detail()} />);
    const rows = screen.getAllByTestId("assets-add");
    const sum = rows.reduce((a, n) => a + Number(n.textContent!.replace("−", "-")), 0);
    expect(sum).toBe(75);
    expect(screen.getByTestId("assets-total").textContent).toBe("+75");
  });

  it("renders EVERY assets signal, unfiltered — a noise floor would break the sum", () => {
    render(<OutlookTab detail={detail()} />);
    expect(screen.getAllByTestId("assets-add")).toHaveLength(3);
  });

  it("names the signal count and the pillar weight in the total row", () => {
    render(<OutlookTab detail={detail()} />);
    expect(screen.getByText(/Assets — three signals × 40% weight/)).toBeTruthy();
  });

  it("keeps rendering when the rating is absent", () => {
    render(<OutlookTab detail={detail({ franchise_rating: null })} />);
    expect(screen.getByText(/Draft needs/)).toBeTruthy();
  });
});
```

- [ ] **Step 21: Run and verify they fail**

```bash
npx vitest --config tests/vitest.config.ts run tests/ownerdeepdive/OutlookTab.test.tsx
```

- [ ] **Step 22: Implement `OutlookTab.tsx`**

Create `web/components/ownerdeepdive/OutlookTab.tsx`:

```tsx
"use client";

import { OwnerDetailResp, PillarBreakdown } from "@/lib/types";
import { DivergeBar, fmtPts } from "@/components/RatingBars";
import { StageLadder } from "../furniture/StageLadder";
import { Panel } from "../furniture/Panel";
import { Row } from "../furniture/Row";
import { Card, CardHead } from "./ui";
import { SIGNAL_LABELS, ordinal } from "./util";
import { RoomsSection } from "./RosterHealthTab";
import { DraftNeedsSection, DraftSection } from "./FutureDraftTab";

/* ---------------------------------------------------------------------------
 * The Outlook tab IS the Assets pillar's page.
 *
 * There is no second model here. The competitive-window stage is a band on the
 * Franchise Rating composite (engine/gm_rating.py::rating_to_stage) and the
 * ledger below is the same Assets breakdown the Overview tab draws for the
 * whole grade — the previous Strength x Trajectory model was a second
 * arithmetic over substantially the same evidence, on an adjacent tab of one
 * page, free to disagree.
 *
 * Five sections: hero, the Assets ledger, draft needs, the rooms chart, draft.
 * ------------------------------------------------------------------------ */

const COUNT_WORDS: Record<number, string> = { 1: "one", 2: "two", 3: "three" };

const UNRATED_COPY: Record<string, string> = {
  first_season: "This is your first season, so there is no grade to build a window from yet.",
  new_franchise: "This franchise has no completed season yet, so there is no grade to build a window from.",
};

/** The reader-legible form of each Assets signal's RAW value. Distinct from
 *  `Adds`, which is the signal's rating-point contribution — the two columns
 *  answer different questions and only the Adds column has to reconcile. */
function figureFor(
  key: string, raw: number, futurePicks: number,
): string {
  switch (key) {
    case "roster_value_share":
      return `${(raw * 100).toFixed(1)}%`;
    case "young_core_share":
      return `${Math.round(raw * 100)}%`;
    case "draft_capital":
      // The raw is a Trade Value total; the pick COUNT is what a reader holds
      // in their head, and the Draft section below carries the value.
      return futurePicks > 0
        ? `${futurePicks} pick${futurePicks === 1 ? "" : "s"}`
        : Math.round(raw).toLocaleString();
    default:
      return String(raw);
  }
}

function signed(z: number): string {
  return `${z >= 0 ? "+" : "−"}${Math.abs(z).toFixed(2)}`;
}

function Hero({ detail }: { detail: OwnerDetailResp }) {
  const fr = detail.franchise_rating;
  const ol = detail.outlook!;
  const assets = fr?.pillars?.assets;

  return (
    <Card>
      <div className="font-mono text-label uppercase tracking-widest text-dim">
        {assets && fr
          ? `Assets — ${Math.round(assets.weight * 100)}% of your ${fr.letter}`
          : "Assets"}
      </div>
      {assets ? (
        <p className="mt-1 font-display text-lead font-bold leading-tight tracking-[-0.03em]">
          Your forward-looking half is worth {fmtPts(assets.contribution)} rating points.
        </p>
      ) : (
        <p className="mt-1 font-display text-lead font-bold leading-tight tracking-[-0.03em]">
          No Assets grade yet.
        </p>
      )}
      <p className="mt-2 max-w-[68ch] text-figure leading-relaxed text-body">
        Results answer what you have done. Assets answer what you can still do — the same
        numbers the grade is built from, not a second model that can disagree with it.
      </p>

      <div className="mt-4">
        <StageLadder stage={ol.window} />
      </div>

      {ol.window == null ? (
        <p className="mt-2 font-mono text-label text-dim">
          {UNRATED_COPY[detail.unrated_reason ?? ""] ??
            "No grade yet, so no window."}
        </p>
      ) : (
        <p className="mt-2 font-mono text-label text-dim">
          Derived, not separately modelled: Results z {signed(ol.results_z ?? 0)}, Assets z{" "}
          {signed(ol.assets_z ?? 0)}.{" "}
          {(ol.tilt ?? 0) > 0
            ? "Assets ahead of Results — the roster is ahead of the trophy case."
            : (ol.tilt ?? 0) < 0
              ? "Results ahead of Assets — the trophy case is ahead of the roster."
              : "Results and Assets are level."}
        </p>
      )}
    </Card>
  );
}

function AssetsLedger({ detail }: { detail: OwnerDetailResp }) {
  const assets: PillarBreakdown | undefined = detail.franchise_rating?.pillars?.assets;
  if (!assets) return null;

  const ranks = detail.outlook?.assets_signal_ranks ?? assets.signal_ranks ?? {};
  const futurePicks = Object.values(
    detail.outlook?.draft_capital.picks_by_season ?? {},
  ).reduce((a, b) => a + b, 0);

  /* EVERY signal, unfiltered. The Overview tab drops signals under a 1-point
     noise floor; doing that here would break the sum the total row asserts. */
  const rows = Object.entries(assets.signals).map(([k, s]) => ({
    key: k,
    label: SIGNAL_LABELS[k] ?? k,
    figure: figureFor(k, s.raw, futurePicks),
    rank: ranks[k],
    points: s.contribution,
  }));

  const scale = Math.max(1, ...rows.map((r) => Math.abs(r.points)));
  /* The total sums what is ON SCREEN, so the rows and the figure above them
     cannot disagree. gm_rating.py rounds each contribution independently, so
     that sum can land a point off the pillar's own figure — said out loud
     rather than papered over, exactly as OverviewTab's TotalRow does. */
  const sum = rows.reduce((a, r) => a + r.points, 0);
  const gap = assets.contribution - sum;
  const cols =
    "grid-cols-[minmax(0,1fr)_58px_44px] min-[701px]:grid-cols-[150px_64px_48px_1fr_52px]";

  return (
    <Card>
      <CardHead
        title="What the Assets pillar is made of"
        right={
          <span className="font-mono text-label uppercase tracking-[0.11em] text-dim">
            points vs a league-average GM
          </span>
        }
      />
      <Panel>
        <Row variant="head" data-testid="assets-ledger-head" className={`${cols} items-center gap-2`}>
          <div>Signal</div>
          <div className="text-right">Figure</div>
          <div className="text-right">Rank</div>
          <div className="hidden min-[701px]:block">vs average</div>
          <div className="hidden min-[701px]:block text-right">Adds</div>
        </Row>
        {rows.map((r) => (
          <Row key={r.key} className={`${cols} items-center gap-2`}>
            <span className="min-w-0 truncate font-display text-name font-bold tracking-[-0.024em] text-ink">
              {r.label}
            </span>
            <span className="text-right font-mono text-figure tabular text-dim">{r.figure}</span>
            <span className="text-right font-mono text-figure tabular text-dim">
              {r.rank != null ? ordinal(r.rank) : "—"}
            </span>
            <div className="hidden min-[701px]:block">
              <DivergeBar points={r.points} scale={scale} />
            </div>
            <span
              data-testid="assets-add"
              className={`text-right font-mono text-figure font-semibold tabular ${
                r.points > 0 ? "text-pos-strong" : r.points < 0 ? "text-neg-strong" : "text-dim"
              }`}
            >
              {fmtPts(r.points)}
            </span>
          </Row>
        ))}
        <Row variant="total" cols="minmax(0,1fr) auto" className="py-2">
          <span className="min-w-0">
            <span className="font-display text-name font-bold tracking-[-0.024em] text-ink">
              Assets — {COUNT_WORDS[rows.length] ?? String(rows.length)} signal
              {rows.length === 1 ? "" : "s"} × {Math.round(assets.weight * 100)}% weight
            </span>
            {gap !== 0 && (
              <span className="mt-0.5 block font-mono text-label font-normal normal-case tracking-normal text-dim">
                pillar above rounds to {fmtPts(assets.contribution)}
              </span>
            )}
          </span>
          <span
            data-testid="assets-total"
            className="whitespace-nowrap text-right font-mono text-figure font-semibold tabular text-ink"
          >
            {fmtPts(sum)}
          </span>
        </Row>
      </Panel>
    </Card>
  );
}

export function OutlookTab({ detail }: { detail: OwnerDetailResp }) {
  if (!detail.outlook) return null;
  return (
    <div>
      <Hero detail={detail} />
      <AssetsLedger detail={detail} />
      <DraftNeedsSection outlook={detail.outlook} />
      <RoomsSection outlook={detail.outlook} />
      <DraftSection outlook={detail.outlook} draftSkill={detail.draft_skill} />
    </div>
  );
}
```

Add `roster_value_share: "Roster Value Share"` to `SIGNAL_LABELS` only if the existing `"Roster Value"` reads wrong beside `young_core_share`'s `"Young Core"` — check the rendered ledger before changing a shared map.

- [ ] **Step 23: Rewire `OwnerDeepDive.tsx`**

Replace the `activeTab === "outlook"` block (`:229-249`) with:

```tsx
        {activeTab === "outlook" && detail.outlook && <OutlookTab detail={detail} />}
```

Delete the imports of `WindowSection`, `RosterHealthTab`, `FutureDraftTab` and — if nothing else on the page uses them — `Card`, `Stat`, `StatStrip` from `./ownerdeepdive/ui`. Add `import { OutlookTab } from "./ownerdeepdive/OutlookTab";`.

Then delete the component and its test:

```bash
git rm web/components/ownerdeepdive/WindowSection.tsx \
       web/tests/ownerdeepdive/WindowSection.test.tsx \
       web/tests/FutureDraftTab.test.tsx \
       web/tests/ownerdeepdive/RosterHealthTab.test.tsx
```

Update `web/tests/OwnerDeepDive.test.tsx`: its fixture at `:86-96` carries `strength_score`, `trajectory_score` and a whole `window_breakdown`. Replace that block with the new `OutlookView` shape (`window`, `results_z`, `assets_z`, `tilt`, `assets_signal_ranks`) and drop any assertion on the deleted section.

- [ ] **Step 24: Run and verify green**

```bash
npx vitest --config tests/vitest.config.ts run tests/ownerdeepdive/ tests/OwnerDeepDive.test.tsx
npx tsc --noEmit
```

- [ ] **Step 25: Commit**

```bash
cd .. && git add -A
git commit -m "feat(web): the Outlook tab becomes the Assets pillar's own page

Five sections against one model. The Assets ledger reuses DivergeBar
rather than ContributionRow — the bar is the grammar, but that row's
three-track grid cannot hold Signal · Figure · Rank · vs average · Adds."
```

## 6f — Standings and methodology

- [ ] **Step 26: Write the failing tests**

In `web/tests/StandingsTable.test.tsx`, replace every `strength_score`/`trajectory_score` fixture field and add:

```tsx
it("has no s/t column and no Strength × Trajectory tooltip anywhere", () => {
  render(<StandingsTable rows={ROWS} leagueId="L" state={DEFAULT_STATE} />);
  expect(screen.queryByText("s/t")).toBeNull();
  expect(screen.queryByTestId("st-value")).toBeNull();
  expect(document.body.textContent).not.toMatch(/Strength/i);
  expect(document.body.textContent).not.toMatch(/Trajectory/i);
});

it("column count and grid track count agree in every gating combination", () => {
  // FRANCHISE_GRID and its three variants are written out in full because
  // Tailwind's JIT only sees literal class names — so a dropped column and a
  // dropped track are two separate edits that must stay in step.
  const tracks = (g: string) => g.slice("grid-cols-[".length, -1).split("_").length;
  expect(tracks(FRANCHISE_GRID)).toBe(FRANCHISE_COLS.length);
});

it("clears a persisted sort on the deleted s/t column", () => {
  render(<StandingsTable rows={ROWS} leagueId="L"
    state={{ ...DEFAULT_STATE, sort: { column: "strength_trajectory", direction: "desc" } }} />);
  // Falls back to the Franchise Rating default rather than sorting on nothing.
  expect(screen.getAllByRole("row")[1].textContent).toContain(ROWS[0].owner.owner_name);
});

it("shows the Window column for a rated dynasty league", () => {
  render(<StandingsTable rows={ROWS} leagueId="L" state={DEFAULT_STATE} />);
  expect(screen.getByText("Window")).toBeTruthy();
});

it("omits the Window column entirely when no row carries one", () => {
  const redraft = ROWS.map((r) => ({ ...r, window: null, draft_capital_value: null }));
  render(<StandingsTable rows={redraft} leagueId="L" state={DEFAULT_STATE} />);
  expect(screen.queryByText("Window")).toBeNull();
});
```

Add a methodology test in `web/tests/MethodologyContent.test.tsx` (create if absent):

```tsx
it("publishes the model that ships, not the retired one", () => {
  render(<MethodologyContent />);
  const text = document.body.textContent ?? "";
  // Case-sensitive on purpose: the Draft Capital entry legitimately says
  // "roster strength" in lower case, and only the capitalised axis NAMES are
  // the retired model's vocabulary.
  for (const dead of ["draft skill", "year-over-year momentum", "Strength",
                      "Trajectory", "Competing now", "Peaking", "Ascending",
                      "Descending"]) {
    expect(text).not.toContain(dead);
  }
  for (const live of ["Retooling", "Contending", "Rebuilding"]) {
    expect(text).toContain(live);
  }
});

it("states the bands' n=12 caveat rather than implying calibration", () => {
  render(<MethodologyContent />);
  expect(document.body.textContent).toMatch(/one league/i);
});
```

- [ ] **Step 27: Edit `StandingsTable.tsx` — all eight sites plus the two the spec missed**

1. `:62` `FRANCHISE_COLS` — delete the `strength_trajectory` entry (`:89-92`) and rewrite the `window` tooltip (`:85-88`):

```tsx
  {
    key: "window", label: "Window",
    tooltip: {
      title: "Roster Window",
      body: "Your competitive stage, banded off the Franchise Rating on this same row — Rebuilding, Retooling, Competing, Contending, Dynasty. Not a separate model: a better rating can never land on a lower stage. Reflects today, not the year filter.",
    },
  },
```

2. `:145` `OUTLOOK_COL_KEYS` → `new Set(["window", "draft_capital_value"])`.
3. `:154-157` — every grid string drops one track:

```tsx
// #, Franchise, Rec, Trophy, Playoff, Rating, [Roster], [Window, Draft cap]
export const FRANCHISE_GRID = "grid-cols-[24px_1.15fr_0.5fr_0.55fr_0.5fr_0.75fr_0.55fr_0.95fr_0.75fr]";
const FRANCHISE_GRID_NO_ROSTER = "grid-cols-[24px_1.3fr_0.55fr_0.6fr_0.55fr_0.8fr_1.0fr_0.8fr]";
const FRANCHISE_GRID_NO_OUTLOOK = "grid-cols-[24px_1.3fr_0.55fr_0.6fr_0.55fr_0.8fr_0.55fr]";
const FRANCHISE_GRID_NO_OUTLOOK_NO_ROSTER = "grid-cols-[24px_1.6fr_0.6fr_0.65fr_0.6fr_0.85fr]";
```

(The last two are unchanged — they never carried the `s/t` track.)

4. `:129-143` — update the block comment: it says the three columns "travel as one group because they read as one — the s/t figures are the receipt for the Window stage". Rewrite: the receipt now lives on the franchise page's Outlook tab, and Window is derived from the Rating column two places left.
5. `:270-273` — delete `formatStrengthTrajectory` entirely.
6. `:629-631` — delete the `data-testid="st-value"` cell.
7. `:533` — nothing to change in the `effectiveSort` logic itself: dropping `strength_trajectory` from `OUTLOOK_COL_KEYS` is what stops a persisted `sort.column === "strength_trajectory"` being caught as orphaned. **Add it to a new clearing set instead**, so the stale key is cleared rather than silently sorting on nothing:

```tsx
  /** Column keys that no longer exist. A saved URL or restored state can still
   *  name one; it must be CLEARED, not left to sort on a field that is gone.
   *  Dropping the key from OUTLOOK_COL_KEYS is what stops it being caught by
   *  the orphan check above. */
  const RETIRED_COL_KEYS = new Set(["strength_trajectory"]);
```

and in `effectiveSort`:

```tsx
    const orphaned =
      RETIRED_COL_KEYS.has(state.sort.column) ||
      (!showOutlook && OUTLOOK_COL_KEYS.has(state.sort.column));
```

8. Verify `web/components/DashboardSkeleton.tsx:116` still lines up — it reads `FRANCHISE_COLS.length` against `FRANCHISE_GRID`, so it is correct only because both changed together. The new test in Step 26 asserts exactly that.

- [ ] **Step 28: Rewrite the methodology entry**

In `web/components/methodology/MethodologyContent.tsx`:

1. **Move the Window entry out of Section 6.** Section 6's lead paragraph asserts these columns are "**not** part of the Franchise Rating formula" — after this change Window *is* derived from the rating, so leaving it there publishes a false framing. Move the entry into the Franchise Rating section (Section 5), after the pillar description.

2. **Placement, corrected during execution:** the entry belongs in the **`Math_`** section (`id="math"`), immediately after the `LETTER_BANDS` table — not "after the pillar description", which pointed at a different section. Both are bands on the same composite through the same `POINTS_PER_SD`, so the stage explanation belongs beside the letter explanation. Leave a line in the `Columns` section saying Window moved and why, so the reference does not dangle.

3. Its new text:

```tsx
        <div>
          <EntryHead
            title="Window"
            formula="Rebuilding · Retooling · Competing · Contending · Dynasty"
          />
          <p className="max-w-[68ch] text-prose leading-relaxed text-body">
            Your competitive stage, banded straight off the Franchise Rating above — the same
            number, cut at the same standard-deviation multiples the letter grades use.
            <span className="text-ink"> Dynasty</span> starts where <span className="text-ink">A−</span> does,
            and <span className="text-ink">Competing</span> spans C− through B−, which is where
            league-average sits by definition. There is no separate window model: a better
            rating can never land you on a lower stage.
          </p>
          <p className="mt-2 max-w-[68ch] text-prose leading-relaxed text-body">
            Like the letter, the stage is a <span className="text-ink">percentile within your
            league</span>, not an absolute scale. The band edges were measured on one league of
            twelve franchises — honestly derived, not proven to hold everywhere.
          </p>
        </div>
```

3. Section 6 keeps `Draft Capital` and whatever else it holds; if Window was its first entry, check the lead paragraph still reads correctly.

**Deliberately NOT generated.** `LETTER_BANDS` is re-exported into this page from `web/.generated/letter-bands.json`, written by `scripts/gen_letter_bands.py` and drift-guarded by `tests/test_letter_bands_export.py`. `STAGE_BANDS` gets **no** such generator, because the entry above states no numeric edge — it states the *alignment* ("Dynasty starts where A− does"), which is a structural claim `test_aligned_with_the_letter_scale` (Task 1) already proves. A generated constant with no consumer is a second thing to keep in sync for nothing. If a later edit puts a number like `1748` on this page, add the generator and the pytest guard **at the same time** — a hand-typed engine constant on the methodology page is exactly the drift that guard exists to catch.

- [ ] **Step 29: Run everything**

```bash
cd web
npx vitest --config tests/vitest.config.ts run
npx tsc --noEmit
npm run lint
cd ..
```

All green, including `furniture-rules.test.ts`.

- [ ] **Step 30: Prove the standings tests bite**

Restore the `strength_trajectory` entry to `FRANCHISE_COLS` without touching `FRANCHISE_GRID` — `"column count and grid track count agree"` must fail. Restore.

- [ ] **Step 31: Commit**

```bash
git add -A
git commit -m "feat(web): standings drop the s/t column; methodology publishes the model that ships

The Window tooltip and the methodology entry BOTH published the retired
formula. The methodology entry also moves out of \"Supporting columns —
not part of the Franchise Rating formula\", which stopped being true the
moment the stage became a band on the rating."
```

---

# Task 7: Verify

Nothing here is optional. QA gates 3, 5, 8 and 9 are only actually tested here.

- [ ] **Step 1: Full suites**

```bash
cd "/Users/tomkeefe/Code Apps/public-dynasty"
pytest tests/ -q
cd api && pytest tests/ -q && cd ..
cd web && npx vitest --config tests/vitest.config.ts run && npx tsc --noEmit && npm run lint && cd ..
```

- [ ] **Step 2: Final per-symbol grep** (QA gate 2, regression)

```bash
for s in compute_strength_score compute_trajectory_score strength_inputs \
         trajectory_inputs classify_window _describe_trajectory WindowInput \
         WindowBreakdown window_input_dict _backfill_yoy WindowSection \
         WINDOW_THRESHOLDS formatWindowRaw strength_trajectory \
         formatStrengthTrajectory WINDOW_CHIP_CLASSES; do
  echo "=== $s ==="
  grep -rn --exclude-dir=node_modules --exclude-dir=.next --exclude-dir=.git \
    --exclude-dir=.claude --exclude-dir=docs "\b$s\b" . | grep -v '^CLAUDE.md:'
done
grep -rn --exclude-dir=node_modules --exclude-dir=.next --exclude-dir=.git \
  --exclude-dir=.claude --exclude-dir=docs "strength_score\|trajectory_score" . \
  | grep -v '^CLAUDE.md:'
```

Expected: **zero hits** everywhere except `docs/superpowers/baselines/`, which is a frozen record.

- [ ] **Step 3: The no-bump bet, against a REAL stale blob** (QA gate 3, blockers)

A fresh cache passes this trivially and proves nothing.

```bash
cp ~/.sleeper-dynasty/cache/chain_9000000000000000001.json /tmp/stale-blob.json
python3 -c "
import json
d = json.load(open('/tmp/stale-blob.json'))
print('schema_version', d.get('schema_version'))
ol = list(d['dynasty_outlooks'].values())[0]
print('has window:', 'window' in ol)
print('has trajectory:', 'trajectory' in ol)
print('has league map:', 'league_avg_age_by_position' in ol['age_profile'])
print('need keys:', sorted(ol['draft_needs'][0]) if ol['draft_needs'] else 'none')
"
```

Then, **without refreshing**, start the API against that cache and check:

| Check | Expected |
|---|---|
| `GET /api/league/{id}` | **200**, never `409 cache cold` |
| `GET /api/league/{id}/owner/{uid}` | 200; Outlook tab renders |
| The rooms chart | absent, with the "league comparison lands here" line — **no exception** |
| Depth pips | absent on every row |
| `outlook.window` | the **derived** stage, never `"Peaking"` |
| Every LLM facts packet | carries the new stage or nothing — grep the cached blurbs for `Peaking` |

- [ ] **Step 4: Refresh the reference league and diff the baseline** (QA gate 0, blocker)

```bash
# Warm through the real path, not a script.
curl -N "http://localhost:8000/api/league/9000000000000000001/refresh"
```

Then:

```bash
python3 - <<'PY'
import json, sys
sys.path.insert(0, "src")
from sleeper_dynasty.engine.gm_rating import rating_to_stage

base = json.load(open("docs/superpowers/baselines/2026-08-18-outlook-window-before.json"))
cache = json.load(open("/Users/tomkeefe/.sleeper-dynasty/cache/chain_9000000000000000001.json"))

# Ratings come from the same live builder both screens read.
sys.path.insert(0, "api")
from app.services.chain_cache import ChainCache
from app.services.franchise_redesign import live_ratings
entry = ChainCache(cache_dir="/Users/tomkeefe/.sleeper-dynasty/cache").read(base["league_id"])
ratings = live_ratings(entry)

print(f"{'owner':>20} {'v1 window':>16} {'rating':>7} {'v2 stage':>12}")
for row in base["rows"]:
    uid = row["user_id"]
    r = ratings.get(uid)
    stage = rating_to_stage(r["rating"]) if r else None
    print(f"{uid[-8:]:>20} {row['window']:>16} "
          f"{(r['rating'] if r else '-'):>7} {str(stage):>12}")

stages = [rating_to_stage(r['rating']) for r in ratings.values()]
from collections import Counter
print("\npopulation:", Counter(stages))
PY
```

Record the table in the commit message. Two things to check, neither of which is "the stages match":

- **Every rung is populated or near it.** The v1 model left two of its five stages never firing in this league; if v2 does the same, re-measure with the `franchise-rating-calibration` skill before shipping.
- **The ordering is sane.** An owner who was `Competing now` under v1 and lands `Rebuilding` under v2 is worth understanding before it reaches a reader; the models measure different things, so disagreement is expected, but a *reversal* against the rating order is not possible by construction and would mean a bug.

- [ ] **Step 5: The two screens agree — walk all twelve** (QA gate 5, blockers; hand check)

Nothing automated proves this. The derivation is shared, which is why it *should* hold, but an owner reading "Contending" on one screen and "Competing" on another is the exact failure this rebuild exists to prevent.

```bash
python3 - <<'PY'
import sys
sys.path.insert(0, "src"); sys.path.insert(0, "api")
from app.services.chain_cache import ChainCache
from app.services.aggregations import build_dashboard
from app.services.owner_view import build_owner_detail
from app.services.leaderboard import build_leaderboard

entry = ChainCache(cache_dir="/Users/tomkeefe/.sleeper-dynasty/cache").read("9000000000000000001")
board = build_leaderboard(entry, year="all")
dash = build_dashboard(entry, year="all", lens="ktc")
standings = {r.user_id: r.window for r in dash.standings}

bad = []
for uid in entry.owners:
    gm = next((r for r in board.rows if r.user_id == uid), None)
    d = build_owner_detail(entry, uid, gm_row=gm, total_owners=len(board.rows))
    page = d.outlook.window if d.outlook else None
    row = standings.get(uid)
    flag = "" if page == row else "  <-- MISMATCH"
    if flag: bad.append(uid)
    print(f"{uid[-8:]:>10}  page={str(page):>12}  standings={str(row):>12}{flag}")
print("\nmismatches:", bad or "none — twelve for twelve")
PY
```

Then confirm by eye in the browser for at least one rated owner and one unrated owner: the ladder lights the same rung the standings row names, and an unrated owner shows an **absence** on both, captioned by `unrated_reason` — no fallback label.

- [ ] **Step 6: Format matrix** (QA gate 8)

| Format | Expected |
|---|---|
| Dynasty | Assets ledger has **three** rows (`roster_value_share`, `young_core_share`, `draft_capital`); Window column present |
| Keeper | **two** rows (`young_core_share` dropped; `0.45/0.20` renormalised over `0.65`); Window column present |
| Redraft | **no Outlook tab at all** and **no Window column** — absence, not an empty pillar |

The redraft case is covered by the fixed-fixture test in Task 5; confirm the dynasty and keeper row counts against real or fixture data.

- [ ] **Step 7: Screen QA — both themes, mobile** (QA gate 6)

At 1280px and 390px, in **both** themes:

- Ladder lights exactly one rung.
- The Assets ledger's visible Adds sum to the total shown. Add them up on screen.
- `Figure` and `Rank` are separate **headed** columns — not `9.8% · 3rd` in one unlabelled cell.
- No needs row for a position with no need.
- Depth pips on the depth branch only; a full-but-aging room shows its reason with no pips.
- Rooms: relative axis, zero labelled as the position's league average, raw age under each dot, labels staggered where they collide, and left-of-centre reads as younger.
- Position codes render in Geist Mono everywhere — `QB` shows no underline.
- No horizontal page scroll at 390px.

`furniture-rules.test.ts` carries **no** rule for label collision or axis correctness. This step is the only thing checking the chart is right.

- [ ] **Step 8: Price the blurb regeneration BEFORE any prod refresh** (QA gate 9, blocker)

`franchise_facts_hash` hashes the pruned packet, which contains `window`, and **every stage name changed** — so the next ungated LLM pass regenerates every franchise blurb in every league.

Invoke the `llm-cost-analysis` skill and price it from `llm_costs.jsonl`:
- per-blurb input + output tokens × the number of rated owners × the number of cached leagues,
- at the current `franchise` model's rates.

Report the figure to the user **before** triggering a prod refresh, not after. Then confirm the offseason gate (`grader.py::llm_pass_throttled`) and the 20h `TRADE_GRADER_LLM_MIN_INTERVAL_SECONDS` throttle still apply, so it is one regen and then quiet — not a daily charge.

- [ ] **Step 9: Update `CLAUDE.md` and the QA artifact**

`CLAUDE.md` changes needed:
- The **Franchise Rating** bullet: add `rating_to_stage`/`_STAGE_SD` beside `rating_to_letter`, and note `PillarBreakdown.signal_ranks` as a read-time `/gm` shape addition.
- The **Owner franchise page** bullet: the Outlook tab is now the Assets pillar's page — five sections, `window` derived at read time, `RosterHealthTab`/`FutureDraftTab` rewritten, `WindowSection` deleted.
- The **League capabilities** bullet: `StandingRow.window` is derived and stays `_outlooks_apply`-gated; `strength_score`/`trajectory_score` are gone with the `s/t` column.
- A one-line note that the CLI exports permanently dropped the Dynasty Window chip and why.

Then update the QA artifact **in place** (a publish without `url:` silently creates a duplicate):

```
Artifact(
  action: "publish",
  url: "https://claude.ai/code/artifact/b9cf990a-764f-41ba-96b1-bee45aac4352",
  file_path: <the updated gates file>,
  favicon: <unchanged>,
)
```

Mark each cleared check and record: the baseline diff table, the twelve-for-twelve screen comparison, and the priced LLM regen.

- [ ] **Step 10: Commit and push the branch**

```bash
git add -A
git commit -m "docs: record the Outlook redesign in CLAUDE.md and close the QA gates"
git push origin outlook-assets-redesign
```

**Do not merge to `main`** — Railway auto-deploys from it, and Step 8's cost figure is the user's call.

---

## Self-review

**Spec coverage.** Every section of rev 3 maps to a task: stage derivation → Task 1; tilt and the unrated case → Tasks 1/5/6e; the facts packet → Task 2; the engine deletion, the dead-input tail and the `window_input_dict` deletion → Task 3; league mean ages, `held`/`ideal` and their routes → Task 4; the API section, `signal_ranks`, the read-time window and the redraft gate → Task 5; the five screen sections, `types.ts`, `window.ts`, `OwnerDeepDive`, `StandingsTable`, `MethodologyContent` → Task 6; persistence, testing, and costs → Tasks 4/5/7. The consumer table's seven rows are all covered, with the extra sites from the review sweep folded in.

**Out of scope, deliberately absent:** Buy/Sell/Hold, redraft Outlook of any kind, restoring a window reading to the CLI exports, per-season Outlook history, and re-measuring `REFERENCE_COMPOSITE_SD`.

**Known deviations, both stated in-line:**
1. `DraftNeed.kind` is added; the spec required pip gating without naming a mechanism, and `urgency` cannot serve because the depth and aging branches both emit `"developing"`.
2. Pips are suppressed on the `_MIN_STARTERS` branch, following the spec and QA gate literally, even though `held < ideal` holds there too. One line changes it if the user wants the information back.
