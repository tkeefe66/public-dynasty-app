# Franchise Command Center — Design Spec

**Date:** 2026-06-13
**Status:** Approved (pending spec review → implementation plan)
**Sub-project:** A of 3 (see "Context" below)

## Context

The `sleeper-dynasty` engine has grown well beyond a trade analyzer into a multi-domain
dynasty intelligence engine, but the UI still tells the "trades" story. A capability audit
identified four analytical domains and how much of each reaches the user:

1. **Trade analysis** — surfaced well.
2. **GM skill rating** — surfaced, but on a secondary tab.
3. **Franchise health / future** (dynasty outlook: age, draft capital, needs) — **CLI-only**.
4. **Season / competition** (standings history, Monte Carlo odds, recaps) — **CLI-only**.

The work was decomposed into three sub-projects, each a value-shipping vertical slice:

- **A — Franchise Command Center** (this spec): upgrade the owner page into a GM cockpit.
- **B — League Intelligence Dashboard**: reframe the landing page from "trade highlights"
  to league-wide competitive intelligence. Reuses A's new API endpoints.
- **C — Season / Competition Layer**: standings history, live Monte Carlo playoff/title
  odds, recaps. Most valuable in-season; deferred.

**Decisions that frame A:**
- Storytelling is a *layer applied everywhere*, not a destination.
- The landing page (B) will be league-wide; the *single-franchise* depth lives on the
  upgraded owner page (this spec). No login / "pick your team" concept is introduced —
  the owner page stays a shareable, no-auth view.
- Live Monte Carlo odds need an in-season schedule + per-player projections that don't
  exist in the offseason, so A uses a **roster-value-rank proxy** for "where this team
  is headed"; true odds are deferred to C.

## Goal

Turn the owner detail page (`/league/[id]/owner/[uid]`, also embedded in the Owners tab)
into a **tabbed franchise command center**: a persistent hero band over four tabs, surfacing
the dynasty-outlook intelligence that currently never leaves the CLI.

### Non-goals
- No Monte Carlo playoff/title odds (sub-project C).
- No "pick your team" / login personalization.
- No dashboard / landing-page changes (sub-project B).
- No changes to the cold-start 409 contract or refresh SSE stages (beyond adding compute).

## UX / Layout

Chosen layout: **tabbed cockpit**. The Overview tab is a *teaser of every domain* so the
depth is visible before clicking — tabs are for depth, not for hiding existence.

### Hero band (persists across all tabs)
- Identity: avatar, owner name, team name (existing `OwnerLabel`).
- Existing context where available: GM rating, trade grade pill, rivals.
- **Four vital stats:** Window · Roster-value rank (`#3 / 12`) · Avg age · Draft-capital status.
- **Franchise-outlook blurb:** 1–2 sentence LLM narrative (see "Franchise blurb").

### Tabs
1. **Overview** — four teaser cards, each linking into its deep-dive tab:
   - *Roster & Health* — avg-age-by-position mini-bars, young-core count, aging-risk count.
   - *Future & Draft* — picks-by-season chips, top draft needs.
   - *Track record* — career-arc sparkline (trade value by season).
   - *Signature deals* — best/worst deal chips.
2. **Roster & Health** — age profile by position, young-core list, aging-risk players,
   roster-value breakdown.
3. **Future & Draft** — draft capital (picks by season & round, net vs league average,
   total pick value, status), draft needs (position, urgency, reason), and **past draft
   skill** (`draft_skill()` score + league rank/percentile).
4. **Trades** — the *entire current owner page* moves here unchanged: five metric tiles,
   full `CareerArc`, best/worst deal cards, complete filterable trades table.

## Architecture (vertical slice)

```
refresh  ──►  engine (dynasty outlook + roster-value rank + draft skill + franchise blurb, per owner)
         ──►  ChainCacheEntry (persisted per owner)
         ──►  GET /api/league/{id}/owner/{uid}  (new optional fields)
         ──►  OwnerDeepDive tabbed Command Center (web)
```

### 1. Engine layer (mostly exists)
- **Dynasty outlook** — `engine/dynasty.py::build_dynasty_outlook()` already returns
  `DynastyOutlook{window, trajectory, age_profile, draft_capital, draft_needs}`. Ensure it
  runs per-owner during refresh and the **full object** is retained (today only the scalar
  signals feed the GM Outlook pillar).
- **Roster-value rank** — new pure helper: rank owners by the already-computed
  `roster_value` outlook signal → `{rank, of}`. Current-league members only.
- **Past draft skill** — `engine/draft_signals.py::draft_skill()` already returns
  `dict[uid → score]`. Persist each owner's score; derive a league rank/percentile for display.
- **Franchise blurb** — new pure facts builder `engine/franchise_outlook.py` +
  writer `llm/franchise_outlook_writer.py` (`claude-opus-4-8`), mirroring the trade-story
  and GM-blurb pattern. Grounded facts: window, trajectory, young core, aging risks,
  draft-capital status, top draft need, signature (best) trade. Eager + incrementally
  generated and cached during refresh. **Skipped gracefully if `ANTHROPIC_API_KEY` is
  unset** — refresh still completes (same contract as trade stories).

### 2. Persistence (`ChainCacheEntry`)
Add per owner:
- `dynasty_outlook` (serialized `DynastyOutlook`)
- `roster_rank: {rank: int, of: int}`
- `draft_skill_score: float | None` (+ derived rank surfaced at API time)
- `franchise_blurb: str | None`

Computed inside the shared `refresh_service.refresh_league` path so both the manual
`/refresh` and the auto-refresh scheduler populate it (one refresh path).

### 3. API layer
Extend `api/app/models/owner.py::OwnerDetailResp` with **optional, backward-compatible**
fields:
- `outlook: OutlookView | None`
- `roster_rank: RankView | None`
- `draft_skill: DraftSkillView | None`
- `franchise_blurb: str | None`

New Pydantic sub-models: `OutlookView` (window, trajectory), `AgeProfileView`
(avg_age_by_position, overall_avg_age, core_young, aging_risks), `DraftCapitalView`
(picks_by_season, picks_by_season_round, net_vs_average, status, total_value),
`DraftNeedView` (position, urgency, reason), `DraftSkillView` (score, rank, of).
`api/app/services/owner_view.py::build_owner_detail` reads them from the cache entry.
All existing fields (`totals_by_lens`, `career_arc`, `trades`, `best/worst_trade_id`,
`owner`) are unchanged.

### 4. Web layer
- Refactor `web/components/OwnerDeepDive.tsx` into a **hero band + tabbed shell**.
- New presentational components: `HeroBand`, `OverviewTeasers`, `RosterHealth`,
  `DraftCapital`, `DraftNeeds`, `DraftSkill`.
- Current sections (`CareerArc`, five tiles, best/worst, trades table) relocate
  **unchanged** into the Trades tab.
- New TypeScript types mirror the new API sub-models.
- Reuse unchanged in both contexts (standalone `/owner/[uid]` page = read-only; Owners tab
  = editable). Editable profile affordance stays Owners-tab-only.
- Tab state is local UI state (optionally URL-synced via a query param for shareability —
  nice-to-have, not required).

## Data flow

`refresh → engine computes {outlook, roster_rank, draft_skill, franchise_blurb} per owner
→ persisted on ChainCacheEntry → GET /owner/{uid} serializes them → tabbed Command Center
renders them`.

## Error handling & graceful degradation

- **Per-owner outlook compute is wrapped/try-logged** — one owner failing never breaks the
  whole refresh; null fields simply hide their sections.
- **Stale cache built before this feature** → new fields arrive null → the page falls back
  to today's Trades-centric content (Overview teasers and the new tabs hide cleanly). No
  409 / cold-start contract change.
- **Blurb absent** (no API key, or not yet generated) → hero shows data-only, no blurb line.
- **Former owners with no current roster** → outlook null → only the Trades tab populates.
- Cold cache still returns 409 until refresh, unchanged.

## Testing

- **Engine:** unit tests for the roster-value-rank helper and the franchise facts builder
  (pure). `DynastyOutlook` and `draft_skill()` already have coverage.
- **API:** `build_owner_detail` populates the new fields when present; backward-compat test
  with a pre-feature cache entry (new fields → null, response still valid).
- **Web:** component renders all tabs; graceful render when `outlook == null`.
- **E2E (Playwright):** owner page loads, hero band renders, tab switching works.

## Open items / future

- Tab state URL-sync for deep-linkable tabs (nice-to-have).
- Sub-project B (League Intelligence Dashboard) will reuse the new outlook/rank endpoints.
- Sub-project C adds live Monte Carlo odds to the hero/Overview in-season.
