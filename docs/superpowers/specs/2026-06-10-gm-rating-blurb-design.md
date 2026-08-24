# GM-Rating Blurb — Design

**Date:** 2026-06-10
**Status:** Approved (pending spec review)

## Goal

At the bottom of each expanded GM-rating breakdown panel (the `/gm` leaderboard
drill-down), show a brief, one-paragraph LLM-written blurb about the owner: who
they are as a GM and why their grade landed where it did. Mirrors the existing
**trade-story** pattern end-to-end.

## Decisions

| Question | Decision |
|---|---|
| **Scope** | **Per scope.** A blurb for each tab — All-time + every season — so it matches the exact numbers on screen. ~12 owners × (seasons + 1) ≈ 60 blurbs on a cold warm-refresh. |
| **Model** | **`claude-opus-4-8`** — same as trade stories. Richest prose / sharpest voice. |
| **Voice** | **Brand persona** — sharp, candid, cocky insider trash-talk (the rivalry-tool voice), strictly grounded in the facts packet. |
| **Sparse data** | **Skip silently** — owner/scope with no graded trades or too few owners to rate gets no blurb; the panel renders exactly as it does today. |

## Architecture (mirrors trade-story pattern)

### 1. Grounded facts — engine

- **New** `OwnerRatingFacts` dataclass (alongside the trade-story facts models).
- **New** `build_owner_rating_facts(scope_label, gm_row_pillars, owner_name, team_name, rank, rating, trend) -> OwnerRatingFacts`.
- Sourced from the **same per-scope pillar breakdown the UI renders** (`compute_gm_ratings` output / `GMRow.pillars`), so the blurb can only cite real numbers.
- Fields: owner name + team, `scope_label` (`"career"` vs e.g. `"the 2025 season"`), rank, rating, trend, per-pillar contribution (outcomes / trade_impact / outlook), the **top 2–3 driving signals** and **worst 1–2** (label + contribution), championships count, made-playoffs signal, outlook standing, and an explicit `draft_capital_counted: false` flag so the model never claims draft capital helped.
- `to_dict()` for the facts packet. Pure, unit-tested.

### 2. Writer — LLM layer

- **New** `GmRatingBlurbWriter` (mirrors `TradeStoryWriter`): `claude-opus-4-8`, constructs `anthropic.Anthropic(api_key=None)` (reads `ANTHROPIC_API_KEY`), ephemeral-cached system persona, facts packet as the user message.
- **New** prompt `src/sleeper_dynasty/llm/prompts/gm_rating_blurb_persona.md` — brand voice; **one paragraph, ~3–4 sentences**; must answer "who is this GM" + "why this grade" (dominant pillar + top signals) + the forward look; **grounded strictly in the facts** (no invented league history); never claim draft capital contributed.
- Returns `{"blurb": str}`. On any API error / missing key → caller skips; refresh still completes.

### 3. Generation + cache — refresh

- **New** `generate_owner_rating_blurbs(...)` in the story-gen service, parallel to `generate_stories`:
  - For each scope (`"all"` + each season in the chain): compute GM ratings for that scope, build `OwnerRatingFacts` per owner present in that scope's leaderboard.
  - **Skip** owners/scopes with no rating (sparse-data → skip silently).
  - **Facts-hash incremental-skip**: `facts_hash` over the *rounded* facts (rating, contributions, rank are already ints); if the prior cached blurb's hash matches, reuse it. Completed past seasons generate once, then skip.
  - Concurrent generation with a semaphore + bounded retry (same shape as `generate_stories`).
- **New** refresh stage in `grader.py` after the rating-signal computation, wrapped in `try/except` that **never fails or blocks refresh** (appends a warning on error, like the trade-story stage).
- **New** cache field on `ChainCacheEntry`:
  ```python
  owner_rating_blurbs: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)
  # scope_key ("all" | str(year)) -> uid -> {"blurb": str, "facts_hash": str, "generated_at": str}
  ```

### 4. API

- `GMRow` gains `blurb: str | None = None`.
- `build_leaderboard(entry, *, year, ...)` already resolves the scope; attaches
  `entry.owner_rating_blurbs.get(scope_key, {}).get(uid, {}).get("blurb")`.
- No new endpoint; the leaderboard response carries it.
- Frontend `GMRow` type gains `blurb?: string | null`.

### 5. Frontend

- In `web/components/Leaderboard.tsx`, the expanded panel renders the blurb
  **below** the existing "Every point is league-relative…" explainer line, in
  **sans** prose (not mono), readable width, `text-ink`.
- Absent blurb (cold cache / `ANTHROPIC_API_KEY` unset / older season not yet
  generated / sparse-data skip) → panel renders exactly as today (no empty box).
- Reveal consistent with the existing panel animation; respects reduced motion.

## Data flow

```
refresh → for each scope: compute_gm_ratings → build_owner_rating_facts
        → facts_hash skip vs prior → GmRatingBlurbWriter (opus, concurrent)
        → ChainCacheEntry.owner_rating_blurbs[scope][uid]
request → build_leaderboard(year) → GMRow.blurb
UI      → expanded panel → blurb paragraph under the explainer
```

## Error handling

- Missing `ANTHROPIC_API_KEY` or LLM failure: blurb stage is caught; refresh
  completes; affected blurbs simply absent. Mirrors the trade-story stage.
- Sparse scope/owner: skipped during generation; no blurb attached.
- Cold cache: leaderboard already returns 409 before any blurb is read.

## Testing

- `build_owner_rating_facts` — pure unit tests (top/worst signal selection,
  scope label, draft-capital flag, sparse skip).
- `GmRatingBlurbWriter` — request-shape test with a stubbed client (mirrors
  `test_trade_story_writer.py`); facts-hash stability test.
- `generate_owner_rating_blurbs` — incremental-skip test (unchanged facts reuse
  prior; changed facts regenerate); sparse-data skip.
- Cache round-trip test for `owner_rating_blurbs` (mirror
  `test_chain_cache_stories.py`).

## Out of scope (YAGNI)

- No per-owner blurb on the owner-detail page (this feature is the `/gm` panel only).
- No streaming/lazy on-expand generation; eager-during-refresh only.
- No model/scope config toggle; the decisions above are fixed.

## Files touched

**New**
- `src/sleeper_dynasty/llm/gm_rating_blurb_writer.py`
- `src/sleeper_dynasty/llm/prompts/gm_rating_blurb_persona.md`
- `OwnerRatingFacts` + `build_owner_rating_facts` (engine/models)
- tests (above)

**Modified**
- `src/sleeper_dynasty/engine/` (facts builder) + `models/`
- `api/app/services/chain_cache.py` (`owner_rating_blurbs` field)
- `api/app/services/story_gen.py` (`generate_owner_rating_blurbs`)
- `api/app/services/grader.py` (refresh stage + cache-entry wiring)
- `api/app/services/leaderboard.py` (attach blurb)
- `api/app/models/leaderboard.py` (`GMRow.blurb`)
- `web/lib/types.ts` (`GMRow.blurb`)
- `web/components/Leaderboard.tsx` (render)
