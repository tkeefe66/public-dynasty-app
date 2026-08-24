# Trade Grader Web App — Design Spec

**Date:** 2026-05-28
**Owner:** Tom
**Status:** Implemented & deployed (Next.js + FastAPI on Railway). This spec is the original design record; see `README.md` for the current architecture.

## Goal

Build a professional, multi-tenant web app on top of the existing Sleeper
trade-history grader. Any visitor enters a Sleeper username, picks one of
their dynasty leagues, and gets a polished interactive report of every
trade graded through three lenses (KTC value, hindsight production,
realized impact) plus per-owner standings.

The app must look professional — comparable to modern sports-data
properties like Cleaning the Glass, Pivot+, The Athletic data pages.
Light default with a dark-mode toggle; desktop-first responsive; every
view deep-linkable.

## Non-goals (v1)

- **Authentication / accounts.** Sleeper data is public; we don't need
  user accounts to ship v1. Visitors look up leagues by username; reports
  are public-by-URL like the existing Sheets reports. Auth can come later
  if we add personal preferences or paid tiers.
- **Real-time updates.** Cached + on-demand refresh is sufficient.
- **Multi-sport.** NFL only (matches the underlying grader).
- **Replacing the CLI.** The `sleeper-dynasty trades` command keeps working
  for power users; the web app is an alternate consumer of the same data.
- **Waiver / free-agent grading.** Inherits the underlying grader's scope.

## Architecture

Three-tier: Next.js frontend → FastAPI backend → Python grader engine.
The existing `sleeper_dynasty` Python package is imported as a library by
the backend; no code is duplicated.

```
Browser ── HTTPS ──> Next.js (Railway)
                       │
                       ├─ /api/* proxies to FastAPI
                       │
                       └─ pages: /, /u/<u>, /league/<id>, /league/<id>/owner/<u>,
                                  /league/<id>/trade/<t>, /methodology

FastAPI (Railway) ──> Python grader engine (existing src/sleeper_dynasty/)
                  ├── Sleeper API (sleeper.app/v1)
                  ├── KTC scraper
                  ├── FantasyCalc API
                  └── FileCache (existing) → mounted Railway volume

Single Railway project, two services:
  - `web`: Next.js (Node)
  - `api`: FastAPI (Python; same repo as the existing grader)
```

**Why two services on Railway:** Vercel is the obvious frontend choice
but the user prefers single-vendor deployment. Railway handles Next.js
fine and keeps backend + frontend logs in one place. If we need
Vercel-specific Next.js features later (image optimization, edge
functions), revisit.

**Caching:** The existing `FileCache` already does 1-year TTL for
completed-season Sleeper data + 1-day TTL for current-season + 1-day TTL
for KTC/FantasyCalc. On Railway, mount a persistent volume at
`~/.sleeper-dynasty/cache` so the cache survives deploys. Cold-start a
new league takes ~30s; warm requests are sub-second.

## Backend API

FastAPI app, async throughout. All endpoints JSON.

```
POST /api/lookup
  body: {"username": "Tkeefe6689"}
  resp: {
    "user_id": "...",
    "leagues_by_season": {
      2026: [{league_id, name, total_rosters, status}, ...],
      2025: [...], ...
    }
  }
  4xx if username unknown.

GET /api/league/{league_id}?year={year|all}&lens={ktc|production|impact}&sort={col}.{asc|desc}&filter[col]={...}
  Returns the data needed for the dashboard. Computed by walking the
  league chain via the existing `build_trade_history` + `grade_trade` +
  `aggregate_owner_records` pipeline. Filtered/sorted by query params
  server-side. Cached aggressively (24h for the underlying chain pull,
  derivative views are cheap to recompute).
  resp: {
    "league": {league_id, name, seasons: [int], total_rosters, last_refreshed},
    "selected_year": int | "all",
    "selected_lens": "ktc" | "production" | "impact",
    "hero_stats": {
      "activity": {value, context},
      "biggest_win": {value, owner, trade_id, context, date, counterparty},
      "biggest_loss": {value, owner, trade_id, context, date, counterparty},
      "most_active": {value, context}
    },
    "standings": [{rank, user_id, display_name, net_ktc, net_production,
                   trades, ps_plus, grade, ...}],
    "latest_trades": [{trade_id, date, week, parties, assets_short, swing_ktc, swing_prod}],
    "records": {biggest_value_swing, biggest_production, most_decisive, most_trades}
  }

GET /api/league/{league_id}/owner/{user_id}?year={...}
  Full owner detail: every trade they participated in, per-lens summary,
  career arc by season.

GET /api/league/{league_id}/trade/{transaction_id}
  Trade detail: every side, every asset, all three lenses broken out,
  the underlying matchup data that built realized impact.

POST /api/league/{league_id}/refresh
  Forces a fresh pull (invalidates relevant cache keys). Returns 202
  with a job id; client polls GET /api/league/{league_id}/status or
  uses Server-Sent Events for progress updates.

GET /api/health
  Liveness/readiness probe for Railway.
```

**Sort/filter semantics on `GET /api/league`:** Server-side filtering
keeps payloads small and lets us share computation across queries. Query
shape uses Express-style brackets:
`?filter[net_ktc][gte]=0&filter[grade]=A,B`.

**Cold-start UX:** First request for a username + league triggers the
full ~30s walk. Frontend shows a multi-step progress bar ("Fetching
2024 trades... resolving picks... grading lens 2 of 3..."). Backend
streams progress via Server-Sent Events so the user has visible
heartbeat. Once complete, the result is cached and subsequent requests
are instant.

## Frontend (Next.js)

App Router. TypeScript strict. Server Components where possible (the
dashboard is mostly static once the data is fetched).

### Routes

```
/                                  Landing — username search
/u/{username}                      League picker — list user's leagues
/league/{id}                       Dashboard (default view)
/league/{id}?year=2024&lens=ktc    Same page, URL holds filter state
/league/{id}/owner/{user_id}       Owner detail
/league/{id}/trade/{transaction_id} Trade detail
/methodology                       Deep-dive on the 3 lenses + math
```

### Page: Landing (`/`)

Hero with single input ("Enter your Sleeper username"). Below: 2-3
sentence pitch — "Grades every trade in your dynasty league three ways:
today's value, points actually scored, real impact on wins." Tiny
mention of methodology link. No marketing fluff.

### Page: League picker (`/u/<username>`)

If the user has one league across all visible seasons, redirect straight
to its dashboard. Otherwise show a list grouped by season. Each league
card shows: name, season, status, member count, and total trades graded
(once the chain has been walked at least once — otherwise just "—").

### Page: Dashboard (`/league/<id>`)

This is the main view; everything else is a drill-down.

**Top bar:** brand (`dynasty.report`), nav (Dashboard / Trades / Owners
/ How this works), dark-mode toggle, "Refresh data" button.

**League header:** League name (big), eyebrow "League · 2023 – 2026",
meta (member count, total trades graded, last refresh time),
"copy share URL" button.

**Year tabs:** `2023 | 2024 | 2025 | 2026 | All Years` (no badges).
The selected year sits in the URL (`?year=2024`). All Years is the
default landing experience for first-visit URLs without `?year`.

**First-visit explainer banner** (dismissed via cookie/localStorage):

> What you're looking at: Every trade in your league is graded three ways
> — Value Today (KTC market value), Points Scored (actual production),
> and Impact (starter usage, wins, playoffs). Green favors that owner;
> red against. Hover any "i" for definitions.
> [Read the full methodology →]

**Lens switcher** above hero stats: `by KTC | by Production | by Impact`.
Default KTC. Affects the four hero stat cards only; standings table
shows all three lenses as separate columns regardless.

**Hero stat cards (4):** Trade Activity, Biggest Win, Biggest Loss, Most
Active. Each card carries:
- Plain-English title (e.g., "Biggest Win")
- Mono subtitle naming the lens ("value swing · KTC")
- The number, colored
- Context line (who, when, counterparty)
- (i) icon → hover tooltip with full definition + formula

**Main grid (60/40):**
- **Owner Standings panel** (left, larger): Sortable + filterable table.
  Two-line column headers — plain English label on top, technical name
  in mono beneath (so newcomers and power users both feel at home).
  Headers clickable to sort (arrow indicator).
  Filter row directly beneath headers: text search on Owner, min/max
  inputs on numeric columns, multi-select pills on Grade. Active
  filters surface as removable chips at the bottom with "clear all".
  Each row clickable → owner detail.
  Columns (left to right): Rank, Owner, Value Swing (`net ktc · today`),
  Points Scored (`net production`), Trades (`total count`),
  Big Plays (`playoff starts +`), Grade (`overall`).

- **Sidebar** (right): Two stacked panels.
  - **Latest** — most recent N trades for the selected year. Each card
    shows date/week, parties, short asset list, and a one-line grade.
    Click → trade detail.
  - **Records** — quick stats for the selected year/all-years: biggest
    value swing, most points gained, most decisive starts, most trades.

### Page: Owner Detail (`/league/<id>/owner/<user_id>`)

Hero: Owner name, headline net stats (across all three lenses
side-by-side, not a single composite). Career arc chart — net KTC + net
production by season. Below the fold:
- "Best Trade" + "Worst Trade" cards with the trade detail summarized.
- Full trade list (filterable, sortable, links to trade detail).
- All-time and per-season records (most decisive starts, etc.).

### Page: Trade Detail (`/league/<id>/trade/<transaction_id>`)

Hero: date, week, league season, parties involved.
Two- or three-column layout (one column per side):
- Received block + Gave block, with assets rendered the same way as
  Sheets (`2024 1st pick (orig: Tom) → Marvin Harrison Jr.` for resolved
  picks).
- The three lens scores broken out per side: snapshot KTC swing,
  hindsight production swing, realized impact (Starter Wks, SPC, WSP, DS,
  PS).
- Inline matchup data backing the realized impact: which weeks the
  received player started, what they scored, whether the team won, etc.

### Page: Methodology (`/methodology`)

Editorial-tone explainer. Covers the three lenses with worked examples
of each, formulas, source data (Sleeper API, KTC, FantasyCalc), known
limitations (KTC's 500-player cap, FantasyCalc covering the gap, the
draft-slot derivation logic), and the blacklist mechanism. Links to the
GitHub repo.

### Visual system

- **Type:** Geist (sans) + Geist Mono (numerics, eyebrows, technical
  labels) + Instrument Serif (italic accent on hero numbers and league
  name). Body 12–14px. Heading scale 18 / 22 / 32 / 52px.
- **Light palette (default):** background `#fafaf7`, surface `#ffffff`,
  ink `#0e0e0e`, dim `#6b6b6b`, divider `#e5e5e0`. Accent green
  `#15803d`, accent red `#b91c1c`, hero green tint `#14532d`. Grade pill
  backgrounds: A `#f0fdf4`/`#bbf7d0`, B `#fefce8`/`#fef08a`,
  C/D `#fef2f2`/`#fecaca`.
- **Dark palette (toggle):** background `#0b0c0d`, surface `#131313`,
  ink `#ededed`, dim `#9b9ba2`, divider `#1f2024`. Accent green
  `#d9f99d` on `#1a2a08`, accent red `#fb7185` on `#2a0808`.
- **Spacing/grid:** 4/8/12/16/20/24/32 step. Card radius 10–14px.
- **Tabular numerics** everywhere a number lives.

### Interaction system

- Year tabs and lens switcher persist to URL query params.
- Sort and filter state on the standings table also persist to URL.
- Dark-mode preference persists to localStorage and respects
  `prefers-color-scheme` on first visit.
- "Refresh data" triggers a backend refresh job with a progress modal
  showing live SSE updates.
- All metric labels carry an (i) icon → tooltip with the technical
  definition + a one-line formula in mono.

### Mobile

Desktop-first; mobile-responsive. Standings table collapses to a
card-per-owner view below ~720px. Hero stats stack vertically. Lens
switcher becomes a dropdown. Sidebar moves below the main panel.

## Data flow (cold cache, first visit)

```
1. Visitor enters username → POST /api/lookup
2. Backend: resolve user_id, fetch /user/{u}/leagues/nfl/{season}
   for each visible season → return league list (cached 1h)
3. Visitor picks a league → GET /league/{id}/...
4. Backend: check cache for grader output
   ├ HIT: return immediately (warm)
   └ MISS: open SSE stream; run build_trade_history → grade_trade →
           aggregate_owner_records, emitting progress events
           ("walking chain", "fetching matchups", "grading 12 of 47")
           Cache the result with 24h TTL on the chain pull
5. Frontend renders the dashboard
6. Year/lens/sort/filter changes are client-side only — no refetch
   unless year=all↔year=N switch (which needs different aggregations
   from the cached chain data; backend recomputes from the cached
   resolved-trades base, sub-100ms)
```

## Performance + budgets

- Cold-start league: ≤ 45 seconds end-to-end including network and grading
- Warm dashboard: ≤ 500ms time to interactive
- Lens / year / filter changes: client-side, instant
- Bundle size budget: < 200KB JS gzipped on the dashboard route

## Error handling

| Condition | Behavior |
|---|---|
| Username unknown | 404 with friendly message and link back to landing |
| Username has zero dynasty-relevant leagues | Helpful empty state, suggest checking the season |
| League ID unknown / not visible to user | 404 |
| Backend timeout during cold-start | Surface the partial state ("we got 3 of 4 seasons; refresh to retry") |
| Sleeper API rate limit / 5xx | Retry with backoff; surface "Sleeper is having trouble" if persistent |
| KTC unavailable | Snapshot lens degrades to 0; banner notes the gap; other lenses unaffected |
| FantasyCalc unavailable | Same — fall back to KTC-only, banner notes it |
| Trade ID not found in cached chain | 404; suggest hitting refresh |

## Caching strategy

- **Chain pull cache key:** `chain:{root_league_id}:v1`. Single key
  covers walk + all transactions + drafts + matchups + KTC + FantasyCalc
  for that league chain. 24h TTL on the aggregate; individual underlying
  Sleeper data uses the existing FileCache TTLs.
- **Aggregations by year:** computed in-memory from the cached chain
  base on each request. Sub-100ms.
- **Refresh:** invalidates the chain key + Sleeper transaction/draft/
  matchup keys for the chain. KTC and FantasyCalc keep their TTL.

## Telemetry (v1, minimal)

Backend logs structured JSON per request: route, league_id, user_id (if
known), cache hit/miss, latency, warnings. Frontend captures pageviews +
error events via a lightweight client (Posthog cloud free tier or
similar — defer the decision; not on critical path).

## Testing strategy

### Backend (FastAPI)

- Unit tests for each endpoint with mocked grader engine, asserting
  response shape + status codes.
- Integration tests that exercise the cache path: cold call writes
  cache, warm call hits it.
- Existing 171 grader tests carry over unchanged (the engine is reused).

### Frontend (Next.js)

- Component tests with Vitest + Testing Library for: standings table
  sort/filter logic, lens switcher state-to-URL sync, year tab switching.
- Visual regression via Playwright on the dashboard, owner detail, and
  trade detail routes — both light and dark modes.
- E2E happy-path test: landing → username lookup → league pick →
  dashboard renders.

### Performance

- Lighthouse CI on every PR; budgets enforced (CLS, LCP, bundle size).

## Out of scope (future work)

- Authentication / personal preferences
- Comparing owners side-by-side
- Charts beyond the owner career-arc (e.g., league-wide trade volume
  over time)
- Push / email notifications for league activity
- Embed widgets ("paste your league standings on your Substack")
- Multi-language support
- Paid tier / subscription
- Cross-league rankings (e.g., "Tom's grade compared to all other Toms")
