# Franchise Score Redesign — Phase 2 Implementation Plan (go-live)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the redesigned Franchise Rating (Results / Skill / Outlook) the LIVE rating under the chosen model **Model 2 "equal_axes"** (Results 0.43 / Skill 0.43 / Outlook 0.14), updating the backend read path, the UI pillar labels, and the LLM blurb pipeline so the whole app reflects the new model coherently.

**Architecture:** Phase 1 already built the redesign math + a parallel assembly service (`api/app/services/franchise_redesign.py`) and chose the model. Phase 2 (a) makes `franchise_redesign` the SINGLE live pillar/rating source and points the two legacy builders at it, (b) relabels the four frontend surfaces that hardcode pillar names/weights, and (c) renames the blurb pillar keys + bumps the prompt version to regenerate highlights. Letter surfaces auto-update (pure `rating_to_letter(rating)`); the separate "Trade Grade" (net_ktc z-score) and `compute_gm_ratings`'s legacy defaults are untouched.

**Tech Stack:** Python 3 (FastAPI backend, shared engine), pytest; Next.js 14 / React / TypeScript / Tailwind (web); Markdown persona prompt + Haiku blurb writer.

## Global Constraints

- **Chosen model is "equal_axes":** Results 0.43 / Skill 0.43 / Outlook 0.14 (`REDESIGN_PILLAR_WEIGHTS["equal_axes"]`), signals `REDESIGN_SIGNAL_WEIGHTS`. Use this everywhere the live rating is computed.
- **Pillar vocabulary is Results / Skill / Outlook** (replacing Outcomes / Trade Impact / Outlook). Backend keys: `results` / `skill` / `outlook`.
- **Never show "KTC" in the UI** — it is "Trade Value" / "Value".
- **Five-metric vocabulary** unchanged: Trade Value / Total Points / Regular Season Points / Playoff Points / Toilet Bowl Points.
- **Letter machinery unchanged:** `rating_to_letter`, `LETTER_BANDS`, BASE/SCALE/CLAMP. Letters derive live from the rating number — no cached letters to recompute.
- **Trade Grade stays separate and unchanged:** `aggregations.py::_letter_grade` (net_ktc z-score → `StandingRow.grade`) is a different metric; do NOT touch it.
- **`compute_gm_ratings` legacy defaults stay:** call it with explicit redesign weights from the live builder; do NOT change the function's default args (keeps it non-breaking for any other caller and for tests).
- **Frontend rule:** interactive web components need `'use client'`; only `next build` catches a missing one or an RSC break — a build is mandatory before deploy (no FE work is "done" without it). Do NOT run `next build` against a live `next dev` tree (corrupts `.next`).
- **Blurb regen contract:** bump `BLURB_PROMPT_VERSION` so cached highlights regenerate; stale highlights persist until a refresh runs (force-refresh to verify in prod).

---

## File Structure

**Backend (single source of truth for the live rating):**
- `api/app/services/franchise_redesign.py` — **modify.** Add `LIVE_MODEL = "equal_axes"` and `live_ratings(entry, *, year="all")` returning the full `compute_gm_ratings` output under the live model. This becomes the one builder.
- `api/app/services/leaderboard.py` — **modify.** Point `owner_pillars`/`all_time_ratings`/`compute_season_ratings`/`build_leaderboard` at the redesign tree via `live_ratings`. Remove the legacy `{outcomes,trade_impact,outlook}` assembly.
- `api/app/services/aggregations.py` — **modify.** Point `_all_time_ratings` at `live_ratings` (delete its inline duplicate pillar builder).

**Frontend (pillar labels / weights / help text):**
- `web/components/ownerdeepdive/OverviewTab.tsx` — **modify.** `PILLARS` keys+labels → results/skill/outlook; extend `SIGNAL_LABELS` with the new skill signals.
- `web/components/Leaderboard.tsx` — **modify.** `PILLAR_ORDER`/`PILLAR_LABELS`/`PILLAR_HELP` → new names, weights, copy.
- `web/components/StandingsTable.tsx` — **modify.** Franchise Rating tooltip weights + pillar names.
- `web/app/methodology/page.tsx` — **modify.** Methodology `PILLARS` names/weights/descriptions.

**LLM blurb pipeline:**
- `src/sleeper_dynasty/llm/prompts/gm_rating_blurb_persona.md` — **modify.** JSON highlight keys + the "three pillars" line → Results/Skill/Outlook.
- `src/sleeper_dynasty/llm/gm_rating_blurb_writer.py` — **modify.** `_PILLAR_KEYS` → `{"Results":"results","Skill":"skill","Outlook":"outlook"}`.
- `api/app/services/blurb_gen.py` — **modify.** Bump `BLURB_PROMPT_VERSION` "2" → "3".

**Tests:** `api/tests/test_leaderboard*.py` / `api/tests/test_aggregations*.py` (extend where they assert pillar keys/ratings), `tests/test_gm_rating_blurb_writer.py` (update pillar-key expectations).

---

### Task 1: Make the redesign tree the single live rating source (backend swap)

**Files:**
- Modify: `api/app/services/franchise_redesign.py`
- Modify: `api/app/services/leaderboard.py`
- Modify: `api/app/services/aggregations.py`
- Test: `api/tests/test_franchise_redesign.py` (extend), and any existing leaderboard/dashboard test that asserts pillar keys

**Interfaces:**
- Consumes: `build_redesign_pillars(entry, trades)` and `compute_redesign_ratings(entry, model, *, year)` (Phase 1), `REDESIGN_PILLAR_WEIGHTS`, `REDESIGN_SIGNAL_WEIGHTS`, `_filter_trades_by_year`, `_aggregate_owner_rows`.
- Produces: `franchise_redesign.LIVE_MODEL = "equal_axes"`; `franchise_redesign.live_ratings(entry, *, year="all") -> dict[str, dict]` (full compute_gm_ratings output, pillars keyed `results`/`skill`/`outlook`). `leaderboard.owner_pillars` removed/repointed; `build_leaderboard` rows keep their display fields (`net_ktc`, `production_*`, `trades`) from `_aggregate_owner_rows` while pillars/rating come from `live_ratings`.

- [ ] **Step 1: Write the failing test**

Add to `api/tests/test_franchise_redesign.py` (the `_entry()` fixture already exists from Phase 1):

```python
from app.services.franchise_redesign import LIVE_MODEL, live_ratings


def test_live_ratings_uses_equal_axes_and_redesign_pillars():
    assert LIVE_MODEL == "equal_axes"
    entry = _entry()
    out = live_ratings(entry)
    # Pillars are the redesign tree, not the legacy one.
    assert set(out["A"]["pillars"]) == {"results", "skill", "outlook"}
    # Equal-axes ranks A (fleeced B) over B.
    assert out["A"]["rating"] > out["B"]["rating"]
    # Matches compute_redesign_ratings under the live model exactly.
    from app.services.franchise_redesign import compute_redesign_ratings
    assert live_ratings(entry) == compute_redesign_ratings(entry, "equal_axes")
```

Add to `api/tests/test_leaderboard.py` (or create it if absent) a test that the live board now exposes redesign pillar keys:

```python
def test_build_leaderboard_exposes_redesign_pillars():
    from app.services.leaderboard import build_leaderboard
    from app.services.franchise_redesign import _entry_for_test  # see note
    entry = _entry_for_test()
    resp = build_leaderboard(entry, year="all", prev_ratings={})
    assert resp.rows, "expected at least one row"
    assert set(resp.rows[0].pillars.keys()) == {"results", "skill", "outlook"}
```

> Note: if `test_leaderboard.py` has no shared entry fixture, reuse the `_entry()` builder from `test_franchise_redesign.py` by importing it, or inline a minimal `ChainCacheEntry` like the Phase 1 fixture (owners A/B, one grade with `snapshot_value_swing` + `production_total`, `outcome_signals`, `outlook_signals`, `lineup_signals`). Keep it minimal but valid.

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=api api/.venv/bin/python3 -m pytest api/tests/test_franchise_redesign.py -k live -v`
Expected: FAIL — `cannot import name 'LIVE_MODEL'` / `'live_ratings'`.

- [ ] **Step 3: Add the single live builder**

In `api/app/services/franchise_redesign.py`, add near the top (after imports):

```python
# The model locked after the Phase 1 comparison (Results 0.43 / Skill 0.43 / Outlook 0.14).
LIVE_MODEL = "equal_axes"


def live_ratings(entry: ChainCacheEntry, *, year: Year = "all") -> dict[str, dict]:
    """The live Franchise Rating: full compute_gm_ratings output (pillars keyed
    results/skill/outlook) under LIVE_MODEL. Single source of truth for the
    leaderboard, the dashboard standings, season ratings, and snapshots."""
    return compute_redesign_ratings(entry, LIVE_MODEL, year=year)
```

- [ ] **Step 4: Repoint leaderboard.py**

In `api/app/services/leaderboard.py`:
- Delete the `owner_pillars` function (lines ~28–43) — it built the legacy tree.
- Replace its imports: remove `from sleeper_dynasty.engine.gm_rating import compute_gm_ratings, rating_to_letter` → keep only `rating_to_letter`; add `from app.services.franchise_redesign import live_ratings`.
- `all_time_ratings` becomes:

```python
def all_time_ratings(entry: ChainCacheEntry) -> dict[str, int]:
    return {uid: r["rating"] for uid, r in live_ratings(entry).items()}
```

- `compute_season_ratings` becomes:

```python
def compute_season_ratings(entry: ChainCacheEntry) -> dict[str, dict[str, int]]:
    seasons = sorted({lg["season"] for lg in entry.chain})
    result: dict[str, dict[str, int]] = {}
    for year in seasons:
        ratings = live_ratings(entry, year=year)
        result[str(year)] = {uid: r["rating"] for uid, r in ratings.items()}
    return result
```

- In `build_leaderboard`, replace `ratings = compute_gm_ratings(owner_pillars(rows, entry))` with `ratings = live_ratings(entry, year=year)`. The rest of `build_leaderboard` (rows from `_aggregate_owner_rows` for display fields, ordering by `ratings[uid]["rating"]`, `PillarBreakdown(**pd)` over `rt["pillars"]`) is unchanged — the pillar dict is now keyed results/skill/outlook and flows through unchanged.

- [ ] **Step 5: Repoint aggregations.py**

In `api/app/services/aggregations.py`, replace the body of `_all_time_ratings` (lines ~312–325) with a delegation, and drop the now-unused `compute_gm_ratings` import if nothing else in the file uses it (keep `rating_to_letter`):

```python
def _all_time_ratings(entry: ChainCacheEntry) -> dict[str, int]:
    """All-time {uid: rating} — delegates to the single live builder."""
    from app.services.franchise_redesign import live_ratings
    return {uid: r["rating"] for uid, r in live_ratings(entry).items()}
```

> Use the function-local import to avoid a circular import (aggregations ↔ franchise_redesign ↔ aggregations for `_filter_trades_by_year`). `franchise_redesign` already imports `_filter_trades_by_year` from aggregations at module load, so import `live_ratings` lazily inside the function.

- [ ] **Step 6: Run tests to verify they pass + no regressions**

Run: `PYTHONPATH=api api/.venv/bin/python3 -m pytest api/tests -q`
Expected: the two new tests PASS. Some EXISTING tests that asserted the legacy pillar keys (`outcomes`/`trade_impact`) or specific legacy rating numbers will now fail — UPDATE those assertions to the redesign keys/numbers (the rating values legitimately change; assert the new keys and the A>B ordering rather than frozen magic numbers). Re-run until green. Do NOT weaken a test to pass — fix it to assert the new correct behavior.

- [ ] **Step 7: Commit**

```bash
git add api/app/services/franchise_redesign.py api/app/services/leaderboard.py \
        api/app/services/aggregations.py api/tests/test_franchise_redesign.py api/tests/test_leaderboard.py
git commit -m "feat(rating): make Results/Skill/Outlook (Model 2) the live Franchise Rating"
```

---

### Task 2: Relabel the frontend pillar surfaces

**Files:**
- Modify: `web/components/ownerdeepdive/OverviewTab.tsx`
- Modify: `web/components/Leaderboard.tsx`
- Modify: `web/components/StandingsTable.tsx`
- Modify: `web/app/methodology/page.tsx`
- Verify: `cd web && npm run build`

**Interfaces:**
- Consumes: backend pillar dicts now keyed `results`/`skill`/`outlook`, with skill signals `trade_value`/`trade_production`/`draft_skill`/`lineup_skill`, results signals unchanged (`championships`/`playoff_depth`/`made_playoffs`/`final_seed`/`points_for_rank`), outlook signals `roster_value`/`draft_capital`/`youth`.
- Produces: UI that labels the three pillars and all signals correctly. No data-shape changes.

- [ ] **Step 1: Update OverviewTab.tsx**

In `web/components/ownerdeepdive/OverviewTab.tsx`, replace the `PILLARS` array (lines ~8–12):

```tsx
const PILLARS: { key: string; label: string }[] = [
  { key: "results", label: "Results" },
  { key: "skill", label: "Skill" },
  { key: "outlook", label: "Outlook" },
];
```

Extend `SIGNAL_LABELS` (lines ~13–21) to cover the new skill signals (keep the existing entries; add these):

```tsx
  trade_value: "Trade Value",
  trade_production: "Trade Production",
  lineup_skill: "Lineup Skill",
```

(`draft_skill`, `championships`, `playoff_depth`, `made_playoffs`, `final_seed`, `points_for_rank`, `roster_value`, `draft_capital`, `youth` already exist and stay. The legacy `playoff`/`regular`/`value`/`toilet` entries can remain harmlessly or be removed — leave them to avoid blank labels on any cached legacy payload mid-deploy.)

- [ ] **Step 2: Update Leaderboard.tsx**

In `web/components/Leaderboard.tsx`, replace `PILLAR_ORDER`, `PILLAR_LABELS`, and `PILLAR_HELP` (lines ~61–89):

```tsx
const PILLAR_ORDER = ["results", "skill", "outlook"];
const PILLAR_LABELS: Record<string, string> = {
  results: "Results", skill: "Skill", outlook: "Outlook",
};
const PILLAR_HELP: Record<string, string> = {
  results:
    "What this franchise has actually achieved: championships, playoff depth, seeds, and scoring. 43% of the rating.",
  skill:
    "How well the owner operates the franchise — trade value won, trade production, draft skill, and weekly lineup decisions. 43% of the rating.",
  outlook:
    "Where the franchise is headed: roster value, draft capital, and youth. 14% of the rating.",
};
```

- [ ] **Step 3: Update StandingsTable.tsx tooltip**

In `web/components/StandingsTable.tsx` (line ~47), replace the Franchise Rating tooltip body:

```tsx
body: "The franchise verdict as a letter: 0.43·Results + 0.43·Skill + 0.14·Outlook, z-scored across the league and scaled to 1500, then graded. Always all-time — not affected by year filter.",
```

(Leave the separate "Trade Grade" tooltip at lines ~70–72 unchanged.)

- [ ] **Step 4: Update the methodology page**

In `web/app/methodology/page.tsx` (lines ~59–75), replace the `PILLARS` array:

```tsx
const PILLARS = [
  { name: "Results", weight: 43, desc: "Championships, playoff depth, made-playoffs rate, final seed, points-for rank" },
  { name: "Skill", weight: 43, desc: "Trade value won + trade production (zero-sum, per-trade), draft skill, and weekly lineup efficiency" },
  { name: "Outlook", weight: 14, desc: "Roster value, draft capital (Trade Value of held picks), and youth" },
];
```

Scan the rest of `methodology/page.tsx` for any prose naming the old pillars or "0.45/0.30/0.25" weights and update to the new names/weights.

- [ ] **Step 5: Build to verify (no live dev server running)**

Run: `cd web && npm run build`
Expected: build succeeds (catches any missing `'use client'` or type error). If a dev server is running, stop it first (a build against a live `.next` corrupts it).

- [ ] **Step 6: Commit**

```bash
git add web/components/ownerdeepdive/OverviewTab.tsx web/components/Leaderboard.tsx \
        web/components/StandingsTable.tsx web/app/methodology/page.tsx
git commit -m "feat(web): relabel Franchise Rating pillars to Results/Skill/Outlook (Model 2 weights)"
```

---

### Task 3: Rename blurb pillar keys + bump prompt version

**Files:**
- Modify: `src/sleeper_dynasty/llm/prompts/gm_rating_blurb_persona.md`
- Modify: `src/sleeper_dynasty/llm/gm_rating_blurb_writer.py`
- Modify: `api/app/services/blurb_gen.py`
- Test: `tests/test_gm_rating_blurb_writer.py`

**Interfaces:**
- Produces: blurb writer parses highlight keys "Results"/"Skill"/"Outlook" → backend keys `results`/`skill`/`outlook`; `BLURB_PROMPT_VERSION = "3"` forces regeneration of cached highlights on next refresh.

- [ ] **Step 1: Update the failing test first**

In `tests/test_gm_rating_blurb_writer.py`, find the test(s) asserting the parsed highlight keys (currently expecting `outcomes`/`trade_impact`/`outlook`) and update expectations to `results`/`skill`/`outlook`. Update any sample JSON in the test to use keys `"Results"`/`"Skill"`/`"Outlook"`. Run it to confirm it now FAILS against the current code:

Run: `api/.venv/bin/python3 -m pytest tests/test_gm_rating_blurb_writer.py -v`
Expected: FAIL (current `_PILLAR_KEYS` maps the old labels).

- [ ] **Step 2: Update `_PILLAR_KEYS`**

In `src/sleeper_dynasty/llm/gm_rating_blurb_writer.py` (line ~26):

```python
_PILLAR_KEYS = {"Results": "results", "Skill": "skill", "Outlook": "outlook"}
```

- [ ] **Step 3: Update the persona prompt**

In `src/sleeper_dynasty/llm/prompts/gm_rating_blurb_persona.md`:
- The JSON `highlights` block (lines ~14–16): change keys to `"Results"`, `"Skill"`, `"Outlook"`.
- The "Write one for EACH of the three pillars: …" line (~44): change to `Results, Skill, Outlook`.
- Scan the persona body for any text describing the pillars as "Outcomes"/"Trade Impact" (e.g. what each pillar means) and update to the new framing: Results = what the franchise achieved; Skill = trade/draft/lineup operating skill; Outlook = where it's headed.

- [ ] **Step 4: Bump the prompt version**

In `api/app/services/blurb_gen.py` (line ~26):

```python
BLURB_PROMPT_VERSION = "3"
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `api/.venv/bin/python3 -m pytest tests/test_gm_rating_blurb_writer.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/sleeper_dynasty/llm/prompts/gm_rating_blurb_persona.md \
        src/sleeper_dynasty/llm/gm_rating_blurb_writer.py \
        api/app/services/blurb_gen.py tests/test_gm_rating_blurb_writer.py
git commit -m "feat(llm): blurb highlights keyed Results/Skill/Outlook + prompt version bump (3)"
```

---

### Task 4: Whole-app verification + deploy

**Files:** none (verification only).

- [ ] **Step 1: Full backend + engine suite**

Run: `api/.venv/bin/python3 -m pytest -q && PYTHONPATH=api api/.venv/bin/python3 -m pytest api/tests -q`
Expected: all green. Confirms the live swap + blurb keys didn't regress.

- [ ] **Step 2: Frontend build**

Run: `cd web && npm run build`
Expected: success (no missing `'use client'`, no type error). Ensure no `next dev` is running against the same tree.

- [ ] **Step 3: Local smoke**

Start backend (`make dev-api`) + web (`make dev-web`), refresh a known league (`GET /api/league/<id>/refresh` — this regenerates blurbs at version 3 and recomputes ratings), then check:
- Dashboard standings letters + `/gm` leaderboard reflect the new (Model 2) ratings and are internally consistent (same uid → same letter on standings, owners rail, owner hero, /gm).
- Owner page → Overview "Why this grade" shows three pillars **Results / Skill / Outlook** with the skill signals (Trade Value, Trade Production, Draft Skill, Lineup Skill) and a one-line highlight per pillar.
- The standings "Franchise Rating" tooltip shows the 0.43/0.43/0.14 wording; the separate "Trade Grade" column is unchanged.
- Compare a couple of owners against the `scripts/compare_franchise_models.py` Model 2 column from Phase 1 — they should match.

- [ ] **Step 4: Deploy**

Commit nothing new here. Merge the Phase 2 branch to `main` and push (auto-deploys both Railway services). The cache schema is already 15 (Phase 1), so no new cold-start — but the `BLURB_PROMPT_VERSION` bump means owner pillar highlights regenerate on the next refresh per league (the auto-refresh scheduler handles it; force-refresh a league to verify in prod). Confirm prod `/gm` + an owner Overview render the new pillars.

---

## Self-Review

**Spec coverage (Phase 2 paragraph of the design + the chosen model):**
- Swap live read path to redesign tree under Model 2 → Task 1 (single `live_ratings` builder; leaderboard + aggregations repointed). ✓
- Consolidate the duplicated pillar builders → Task 1 (both delegate to `live_ratings`; legacy `owner_pillars` + inline aggregations builder removed). ✓
- Update Overview "Why this grade" UI → Task 2 (OverviewTab keys/labels + signal labels). ✓
- Update all pillar-naming surfaces → Task 2 (Leaderboard, StandingsTable tooltip, methodology). ✓
- LLM pillar-highlight keys + `BLURB_PROMPT_VERSION` bump → Task 3. ✓
- `next build` before deploy → Task 2 Step 5 + Task 4 Step 2. ✓
- Letters/season-ratings/snapshots auto-update (no cached letters; season ratings + snapshots flow through `live_ratings`) → verified in recon, exercised in Task 4 smoke. ✓
- Trade Grade + `compute_gm_ratings` defaults untouched → Global Constraints; no task modifies them. ✓

**Placeholder scan:** Task 1 Step 6 says "update those assertions" without quoting each legacy test — unavoidable (the exact failing assertions surface only at run time); the instruction is concrete (assert new keys + A>B ordering, not frozen magic numbers). Task 2 Step 4 and Task 3 Step 3 ask to "scan for other prose" — bounded, file-scoped sweeps, not open-ended. No "TODO"/"add error handling" gaps.

**Type consistency:** pillar keys `results`/`skill`/`outlook` consistent across backend (`compute_redesign_ratings`/`build_redesign_pillars` from Phase 1), `GMRow.pillars`/`FranchiseRatingView.pillars` (dict-keyed, model-agnostic — recon confirmed), OverviewTab/Leaderboard `PILLAR_*`, and `_PILLAR_KEYS`. Skill signal keys (`trade_value`/`trade_production`/`draft_skill`/`lineup_skill`) match Phase 1's `REDESIGN_SIGNAL_WEIGHTS["skill"]` and the SIGNAL_LABELS additions. `live_ratings` return shape (full compute_gm_ratings output) matches what `build_leaderboard` consumes (`rt["rating"]`, `rt["pillars"]`).
