# Trade Story — Design Spec

**Date:** 2026-06-07
**Branch:** `worktree-feat+trades-section`
**Status:** Design — pending user review before implementation plan

## Problem

The trade detail page presents raw per-side numbers but never tells the reader
anything. For an audience that is still learning fantasy analytics, "Value swing
+312" and acronyms like `SW / SPC / WSP / DS / PS` mean nothing, and the page
never answers the only question they came with: **who won, and why should I
care?** Numbers alone make people go "meh."

Critique snapshot for the current UI:
`web/.impeccable/critique/2026-06-08T03-15-57Z__web-components-tradesidepanel-tsx-tradestab.md`
(scored 22/40; P0s = "no verdict" and "jargon wall").

## Goal

Turn each trade into a short, **bold, opinionated, funny story** that:

1. **Settles the argument** — leads with a clear verdict (who won).
2. **Reads the owner** — frames the trade as a move within that manager's
   inferred strategy (win-now vs rebuild, "sells picks for vets," etc.) and what
   it means for their team going forward.
3. **Stays grounded in receipts** — every number the story references is
   engine-verified. The *take* can be spicy and occasionally wrong (that's funny
   in a friend group); the *facts* are never wrong.

This is the brand's two jobs at once: settle the argument **and** fuel the trash
talk.

## Decisions locked during brainstorming

| Decision | Choice |
|---|---|
| Story source | **System-inferred** from data. No manual owner profiles (the `OwnerProfile` fields stay empty; not used here). |
| Voice | **Bold, opinionated, funny.** Confidence dials per trade by lopsidedness: brutal when lopsided, "too close to call" (still spicy) when even. |
| On-page format | **Format A** — bold verdict headline + one spicy story paragraph; the numbers ("receipts") live behind a "Show the receipts" disclosure. Story is the hero. |
| Generation method | **Mirror the existing recap pattern**: grounded facts packet → Claude writer that uses ONLY packet facts. |
| Generation trigger | **Eager**, but **incremental** (facts-hash gated) and **concurrent**. First refresh pays the full cost; later refreshes only (re)generate changed/new trades. |
| Owner strategy unit | **Two-tier** — one `OwnerStrategyFacts` dossier per owner (~10), reused across all that owner's trades. |
| Scope | Trade **detail page only** for v1. |

## Why this is low-risk

The codebase already ships this exact pattern for weekly recaps:

- `src/sleeper_dynasty/engine/recap.py` — `FactsBuilder`: pure functions that
  compute "every comedy-relevant number … so the LLM writer never has to (and
  can never invent one)."
- `src/sleeper_dynasty/models/recap.py` — typed facts-packet dataclasses with
  `to_dict()`.
- `src/sleeper_dynasty/llm/recap_writer.py` — `RecapWriter`: static
  prompt-cached persona + facts JSON; "joke ONLY about facts present here."
  `claude-opus-4-8`, reads `ANTHROPIC_API_KEY` from env.
- `src/sleeper_dynasty/llm/prompts/analyst_persona.md` — the persona.

The granular per-game data the stories need **already flows through the grader**
(`engine/trade_grader.py::grade_realized_impact` iterates every post-trade week,
per player, with that player's weekly points, starter flag, decisive-game flag,
and a playoff-week flag) — it is currently aggregated into season totals and
discarded. No new Sleeper API integration is required.

## Architecture

```
refresh (SSE cold-start) → grade chain  [existing]
  ├─ build OwnerStrategyFacts  (1 per owner, from full league-chain history)
  └─ for each trade:
        build TradeStoryFacts  (verdict + player arcs + picks + is_offseason
                                + the two owners' strategy facts inlined)
        facts_hash = hash(facts)
        if cached story for trade_id has same facts_hash: skip   ← incremental
        else: TradeStoryWriter(facts) → markdown story → cache
  → ChainCacheEntry.trade_stories[trade_id] = {verdict, body_markdown,
                                               facts_hash, generated_at}
  → API serves story in TradeDetailResp → Format A on the page
```

### Engine: two grounded fact-builders

New, pure, fully unit-testable (the recap builders are the template).

**`engine/owner_strategy.py` → `OwnerStrategyFacts`** (one per owner)
Derived from the owner's full trade history + career arc:
- `picks_acquired`, `picks_sent`, `net_picks`
- `trades_count`, `trades_per_season`
- `picks_for_players_count` vs `players_for_picks_count` (win-now vs rebuild tilt)
- `career_arc` summary (improving / sliding / treading water — from
  `SeasonArc`/standings already computed)
- `tendencies`: short verified flags, e.g. `"sold a 1st in 3 of last 4 deals"`
  (computed, not prose)

**`engine/trade_story.py` → `TradeStoryFacts`** (one per trade)
- `is_offseason: bool`
- `winner_user_id | "even"`, plus margins per lens (`ktc`, `production`,
  `impact`) and a `lopsidedness` score (0–1) that drives voice intensity
- per **key player** in the trade, a `PlayerArc`:
  - `season_high` (points + week + whether playoff)
  - `playoff_vs_regular_pct` (e.g. −58%)
  - `decisive_starts`, `games_missed`, `starter_weeks`
  - which side received them, points since the trade
- per **pick** traded: what it became (`pick → rookie name`, pts/game) where
  resolvable (reuse `AssetRender`/trade-history resolution)
- `owners`: the two `OwnerStrategyFacts` dossiers inlined

**`models/trade_story.py`** — dataclasses (`PlayerArc`, `PickOutcome`,
`OwnerStrategyFacts`, `TradeStoryFacts`) each with `to_dict()`, mirroring
`models/recap.py`. `facts_hash` is a stable hash of `TradeStoryFacts.to_dict()`.

### LLM writer

**`llm/trade_story_writer.py`** — `TradeStoryWriter`, sibling of `RecapWriter`:
- static persona system block (prompt-cached) + user turn carrying the facts JSON
- instructed to use ONLY packet facts and to scale confidence by `lopsidedness`
- returns markdown: a one-line **verdict** + 1–2 short paragraphs
- raises `anthropic.APIError` subclasses; callers handle (see error handling)

**`llm/prompts/trade_story_persona.md`** — new persona: bold, opinionated, funny,
insider voice (Linear/Vercel-fast, trash-talk, never corporate). Encodes the
"facts-only," "name a winner unless truly even," and "dial by lopsidedness"
rules. No em dashes per house style.

### Caching & generation

- Extend `ChainCacheEntry` (`api/app/services/chain_cache.py`) with
  `trade_stories: dict[str, dict]` and `owner_dossiers: dict[str, dict]`
  (default `field(default_factory=dict)`). Backward compatible: a pre-migration
  cache file simply lacks them → treated as empty → generated on next refresh.
- **Incremental:** skip generation when `trade_stories[tid].facts_hash` matches
  the freshly computed `facts_hash`.
- **Concurrent:** generate missing/changed stories with bounded parallelism
  (e.g. a thread pool, max ~5 in flight) so the first refresh of a long league
  history completes in reasonable wall-clock time.
- **Progress:** emit per-story progress events on the existing SSE refresh
  stream so the `ProgressModal` shows "writing trade stories … N/M."

### API

- `api/app/models/trade.py`: `TradeDetailResp` gains `story: TradeStory | None`
  (`verdict: str`, `body_markdown: str`, `generated_at: str`) and
  `is_offseason: bool`. `LatestTrade` (list view) gains `is_offseason: bool`.
- `api/app/services/trade_view.py::build_trade_detail` reads the cached story
  from the `ChainCacheEntry` (eager model → it is already present). If somehow
  absent (e.g. generation failed for that trade), `story` is `null` and the
  frontend falls back to the receipts-only view.
- **Offseason** derivation lives in the engine (the trade builder), surfaced on
  both responses, fixing the "Week 1" mislabel everywhere it appears. The
  current type carries only `week: number` with no offseason flag, so the exact
  derivation rule must be confirmed against real Sleeper transaction data during
  implementation — likely comparing the transaction date to the season's Week 1
  kickoff (offseason trades land before it), with Sleeper's `leg`/week as a
  secondary signal. See Open questions.

### Frontend (Format A)

- Rework `app/league/[id]/trade/[tid]/page.tsx`; retire the nested-card
  `TradeSidePanel` in its current form.
- New **`components/TradeStory.tsx`**:
  - bold **verdict headline** — winner named in words and colored, margin in
    plain language ("Mike won this one — +1,840 in market value")
  - the **story paragraph(s)** (rendered from `body_markdown`)
  - a **"Show the receipts"** disclosure revealing a **de-nested,
    plain-language** version of the per-side numbers: no nested cards, no
    acronym soup. Real labels ("Starter Weeks," "Points When Started," "Decisive
    Starts," "Playoff Starts") with tooltips; key player arcs surfaced.
- **States:** loading/"writing the story…" only matters if a story is ever
  missing at view time (rare under eager); otherwise render immediately. Error /
  null-story falls back to the receipts view with no story.
- **Accessibility:** win/loss never by color alone — pair with sign + word.
  Responsive: panels stack on mobile (`grid-cols-1 md:grid-cols-2
  lg:grid-cols-3`), the acronym row is gone.
- **`components/TradeCard.tsx`** (list): apply the offseason-label fix; optional
  humanized one-line verdict teaser.

## Error handling

- LLM failure for a given trade during refresh: log, leave that trade's story
  unset, continue the rest. The page degrades to receipts-only for that trade.
- Missing `ANTHROPIC_API_KEY`: refresh still completes graded; stories are
  skipped with a warning surfaced in `ChainCacheEntry.warnings` and the existing
  warnings channel.
- Rate limits / timeouts: bounded concurrency + the SDK's retries; a trade that
  still fails is left unset (above), not retried forever.

## Testing (TDD)

- **Engine builders** (pytest, like `tests/test_recap*`): fixture matchup data →
  assert verdict, margins, `lopsidedness`, `is_offseason`, `PlayerArc` numbers
  (season-high week, playoff split %, decisive starts), pick outcomes, and
  owner-strategy signals. Pure, no network.
- **Writer**: assert `build_request` shape (persona cached, facts-only user
  turn, lopsidedness present); mock the Anthropic client — **no live API call in
  tests**.
- **Cache**: incremental skip when `facts_hash` matches; migration from a
  pre-field cache file.
- **Frontend** (vitest): `TradeStory` renders verdict, toggles the receipts
  disclosure, shows the offseason label, and pairs color with sign+word.

## Config / deployment

- Backend (`api/`) service needs `ANTHROPIC_API_KEY` (Railway env var) — same
  key the CLI already uses. Document in `.env.example` and the Railway service.
- Model: `claude-opus-4-8` (matches the recap default); configurable.

## Out of scope (v1, YAGNI)

- No manual strategy/profile editing (system-inferred only).
- No "rewrite this story" / regenerate-on-demand UI.
- Stories on owner pages or the dashboard (trade detail page only).
- Multi-lens toggle inside the story (verdict uses the primary KTC framing; the
  receipts disclosure shows all three lenses).

## Open questions

- **Offseason derivation rule** (above): confirm against real Sleeper
  transaction data what distinguishes an offseason trade from a Week 1 trade
  before coding the `is_offseason` logic. This is a small investigation at the
  start of implementation, not a design blocker.
- **"Key player" selection** for `PlayerArc`: the packet includes every player
  in the trade; the writer foregrounds the ones with the biggest post-trade
  impact. No selection logic needed in v1.

Voice fine-tuning happens in the persona prompt during implementation and can be
iterated after the first real outputs.
