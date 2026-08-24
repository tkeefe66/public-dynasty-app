# Sleeper Dynasty

Tools for analyzing [Sleeper](https://sleeper.com) fantasy-football leagues — **dynasty, keeper, and redraft**. The project has two faces:

1. **`sleeper-dynasty` CLI** — a Python tool that pulls a league's full season chain: simulates the season (`analyze`), grades every historical trade (`trades`), and generates a savage weekly recap + outlook (`recap`). Emits shareable Google Docs / Sheets / HTML reports.
2. **Trade Grader web app** — a multi-tenant Next.js + FastAPI app that wraps the same grader: enter a Sleeper username, pick a league, and get an interactive report of every trade graded on five metrics, per-owner standings, per-owner **franchise pages**, and a **Franchise Ratings** leaderboard (a letter grade per owner). Dynasty and keeper leagues score on the two-pillar Results/Assets model; redraft leagues — no roster carryover, no dynasty asset value — score on **Results alone** and price trades off redraft-specific market values instead of dynasty ones.

Both share one grading engine: the `src/sleeper_dynasty/` Python package.

---

## Architecture

Three-tier monorepo. The CLI and the web backend both import the same engine.

```
┌─────────────────────────────────────────────────────────────┐
│  web/        Next.js 14 (App Router, RSC, Tailwind)           │
│              server-side proxy: /api/* ──► API_URL/api/*       │
└───────────────────────────────┬───────────────────────────────┘
                                 │ HTTP (JSON + SSE)
┌───────────────────────────────▼───────────────────────────────┐
│  api/        FastAPI + uvicorn + Pydantic v2 + sse-starlette   │
│              thin HTTP layer over the engine; ChainCache on a   │
│              persistent volume so pulls survive deploys         │
└───────────────────────────────┬───────────────────────────────┘
                                 │ import (editable install)
┌───────────────────────────────▼───────────────────────────────┐
│  src/sleeper_dynasty/   engine + models + Sleeper/KTC/FC API    │
│                         clients + FileCache + Google/HTML output │
│                         (also exposed directly as the CLI)      │
└─────────────────────────────────────────────────────────────────┘
```

**Ingestion is platform-pluggable.** `src/sleeper_dynasty/api/platform.py` defines `LeaguePlatform`, the contract every fantasy platform implements — the league chain, rosters, matchups, playoff phases, trades, drops, and draft results, all normalized before they reach the engine. `SleeperClient` implements it today. A Yahoo adapter for redraft/keeper leagues is partially built and currently blocked on Yahoo granting Fantasy API access; see `docs/superpowers/plans/2026-08-11-yahoo-ingestion-protocol.md`. Which platform a league belongs to is derived from the shape of its id, so nothing else in the system carries a platform column.

Every trade is scored on **five metrics** (used by both CLI and web), rolled up per-owner. **Trade Value is a zero-sum swing; the four production metrics are received-only tallies** — points scored by the assets a side *received*, while on that side's roster (no "phantom given" subtraction), so a trade reads head-to-head ("104 vs 56"):

- **Trade Value** — today's KeepTradeCut market-value swing (the one swing metric; shown as "Value" in the UI, never "KTC").
- **Total Points** — received-only points scored since the trade, bench included.
- **Regular Season Points** — received-only started points before the playoff threshold.
- **Playoff Points** — received-only started points in **live title-path winners-bracket games** only (bracket-aware: byes/eliminated weeks count 0; placement games don't count).
- **Toilet Bowl Points** — received-only started points in any losers-bracket game.

The web hero-card *verdict* picks one of two lenses — **Trade Value** or **Production** — but the five metrics above are the headline vocabulary everywhere. The trade detail page renders each side as a **per-player stat table**, where each received asset tells its **journey** (kept, or flipped → linked to that trade → what it became). A league-relative **Franchise Rating** — the two-pillar Results/Assets composite expressed as a **letter grade** (off a 1500-centered number) — is the owner verdict shown platform-wide (standings, owners rail, owner page, and the Franchise Ratings tab); see below.

### Layout

| Path | What it is |
|---|---|
| `src/sleeper_dynasty/` | Core engine. `api/` (Sleeper/KTC/FantasyCalc clients), `engine/` (simulator, trade history, grader, recap), `models/`, `output/` (Google Docs/Sheets, HTML), `cache.py` (`FileCache`), `cli.py`. |
| `api/` | FastAPI backend. `app/routes/` HTTP endpoints, `app/services/` (grader runner, chain cache, view builders), `app/models/` Pydantic response shapes. Installs the engine editable. |
| `web/` | Next.js 14 app. `app/` routes, `components/`, `lib/` (API client, types, URL state). |
| `tests/` | CLI/engine pytest suite. |
| `api/tests/` | Backend pytest suite (`httpx.AsyncClient`). |
| `web/tests/` | Frontend unit tests (Vitest + Testing Library). |
| `web/e2e/` | Playwright smoke tests. |
| `.design/` | **The design system.** Generated, and the source of truth for every design value — tokens, the six self-hosted variable font builds, the logo, 22 component primitives with per-component prompts, and four copyable templates. Start at `.design/SKILL.md`. Note its own docs cite a `ui_kits/` directory of drawn product screens that is **not in the shipped package** — see the defect table in the `design-system-sync` skill. |
| `docs/superpowers/` | Design specs + implementation plans (historical build artifacts — see note below). |

> **Note:** `docs/superpowers/` holds point-in-time specs and plans from the build phases. They record *how* the project was designed and are accurate to what shipped, but they are not living documentation — this README and `CLAUDE.md` are the current source of truth.

### Design system

The app ships **Furniture** (cobalt `#2f42ff`, Bricolage Grotesque in mixed case, 40px rule pitch, 16px radius, one elevation, solid panels whose rows draw their own rules). `web/app/globals.css` `@import`s five token files out of `.design/tokens/` and declares **no value of its own** — a literal colour, size, weight or duration anywhere in `web/` is drift, because it cannot be changed from the place that owns it. `.design/` is generated: changes go through the design project, not this repo (`DESIGN_SYSTEM.md`).

Two skills carry the rules — `furniture-styling` for any UI work in `web/`, `design-system-sync` for wiring or re-syncing `.design/` itself.

**The port is complete**, though the drift guard does not read quite everything: measured, `web/tests/furniture-rules.test.ts` covers **136 of the 141** files under `web/{app,components,lib}`. `UNSCOPED` being empty means no directory is *awaiting* porting — it is not the same as full coverage. `web/app` is not a scoped directory, and flat `web/components` files are listed individually. `web/components/agate/` is deleted, `.ruled` is gone from `globals.css`, and the primitives live in `web/components/furniture/`.

The guard is worth understanding before you trust it: it is a floor, not a definition. It bans a fixed list of patterns, and for most of the migration it had no rule for off-scale type sizes — 52 of them survived in 16 files while it reported green. It resolves paths against the repo root rather than vitest's CWD, and fails if a non-empty scope list yields no files, because it once scanned nothing and passed.

**Two predecessors are retired** and their docs carry banners saying so: **Agate** (`design_handoff_agate/`, retired 2026-08-13) and **The Ledger** (root `DESIGN.md`). Four rules survived all three systems: no colour on data, figures reconcile with the rows beneath them, colour is identity rather than ranking, and never render "KTC" — it is *Trade Value*.

---

## Quick start

### Prerequisites

- Python 3.11+
- Node.js 20+
- (CLI only) Google API credentials if you want Docs/Sheets output
- (`recap` only) An Anthropic API key (`ANTHROPIC_API_KEY`)

### Install

```bash
# Engine + CLI (from repo root)
pip install -e ".[dev]"

# Backend (installs the engine editable as a dependency)
pip install -e "./api[dev]"

# Frontend
cd web && npm ci
```

---

## CLI usage

The engine is exposed as the `sleeper-dynasty` command (entry point in root `pyproject.toml`).

```bash
# Simulate a season and produce an analysis report
sleeper-dynasty analyze <username> [--season 2026] [--week 1] [--sims 10000] [--no-cache]

# Grade every historical trade in the user's dynasty league chain
sleeper-dynasty trades <username> [--season 2026] [--no-cache] [--refresh-trades] [--private]

# Generate a weekly recap + outlook (see section below)
sleeper-dynasty recap <username> [--season 2025] [--week 9] [--lore lore.md] [--persona ...] [--model ...] [--out ...]
```

- `--season` — entry-point season; the grader walks `previous_league_id` back to league origin from here.
- `--no-cache` — invalidate all caches before running.
- `--refresh-trades` — (trades only) invalidate just trade/draft/matchup caches, keep player + KTC caches.
- `--private` — (trades only) keep the generated Google Doc private.

Cache lives at `~/.sleeper-dynasty/cache` by default.

### Weekly Recap & Outlook

Generate a savage, ESPN-parody-analyst recap of the past week plus an outlook
on the upcoming week.

```bash
export ANTHROPIC_API_KEY=sk-ant-...

# Scaffold a league-lore file (inside jokes, nicknames, rivalries):
sleeper-dynasty recap <username> --init-lore lore.md
# ...edit lore.md...

# Generate the recap (defaults to last completed week):
sleeper-dynasty recap <username> --season 2025 --week 9 --lore lore.md
```

Flags: `--week`, `--lore`, `--persona` (override the voice), `--model`
(default `claude-opus-4-8`), `--out`. External data (NFL schedule, weather)
is best-effort — if a source is down, those jokes are simply omitted.

---

## Web app — local development

The frontend proxies `/api/*` to the backend via Next.js rewrites, so run both.

```bash
make dev-api    # uvicorn on :8000  (cd api && uvicorn app.main:app --reload --port 8000)
make dev-web    # next dev on :3000 (cd web && npm run dev)
```

Open http://localhost:3000.

**Cold-start flow:** the dashboard endpoints return `409 cache cold` until a league chain has been pulled. The frontend kicks off `GET /api/league/{id}/refresh` (Server-Sent Events) which streams progress and persists the result to the `ChainCache`; subsequent reads are served from cache.

**Incremental refresh:** a league is built fully once; later refreshes reuse the prior `ChainCacheEntry` rather than re-grading frozen history. When it's the NFL offseason / between weeks and there are no new trades since the last build, the backend copies the prior entry's expensive historical rollups (production series, injury, historical rating signals) and only recomputes the cheap "as-of-today" value layer (Trade Value, outlooks, ratings). New trades, a live scoring week, or a forced refresh trigger a full rebuild. This depends on the API's persistent cache volume so the prior entry survives deploys — without it, every deploy cold-starts every league.

### Trade stories

During the SSE refresh, the engine builds a grounded per-trade facts packet (winner, player post-trade arcs, owner-strategy signals) and a Claude writer (`claude-haiku-4-5-20251001`, the existing recap pattern) turns it into a short verdict and story, cached in the `ChainCacheEntry` and shown on the trade detail page. Generation is eager but incremental (only new or changed trades) and best-effort: a failure never fails the refresh, it just skips that story. Requires `ANTHROPIC_API_KEY` in the backend environment; if the key is absent, refresh completes normally and trade stories are omitted with a warning.

The facts packet carries both the trade-**Value** winner and a **production** head-to-head (cumulative points the haul scored, following the lineage chain), so a story can name the tension when they diverge ("close on value, blowout on the field"). Owner-strategy tilt is **point-in-time** — each story sees the pattern an owner had established *before* that deal, never trades made after it. Two guards keep prose honest: a deterministic sanitizer strips the internal term "KTC" (it's always "Trade Value" to readers), and a `STORY_PROMPT_VERSION` folded into the regen skip-hash forces a one-time rewrite of every cached story when the prompt itself changes (the facts hash alone won't move on a prompt-only edit).

LLM cost control has two layers on top of the coarsened skip-hash (`sleeper_dynasty/models/_signature.py`). An **offseason gate**: when the refresh's incremental-reuse condition holds (offseason and no new trades), the pass reuses all cached prose verbatim — brand-new trades still generate — so offseason LLM spend is ~zero. A **time throttle**: outside the gate, prose regenerates at most once per `TRADE_GRADER_LLM_MIN_INTERVAL_SECONDS` (default 20 hours). Every call is logged with token counts and dollar cost to `llm_costs.jsonl` in the cache dir, rolled up per league on the admin page.

### Became grade (trade lineage)

Beside each trade's *direct* grade (what a side received), the trade detail page shows a parallel **"what it became"** grade — the same five metrics recomputed on the **terminal players** that side's assets eventually turned into. The terminal set comes from a bounded "anti-spiderweb" walk (`engine/lineage.py`, shared with the lineage tree): a received **player** gets exactly one flip (the results are terminal), a **pick** is followed through flips/drafts until it resolves to players, and a terminal player traded onward belongs to a *new* trade's story. Trade Value (became) is the current market value of the terminal players (plus pick value for branches still ending on an undrafted pick); the points metrics (Total, Regular Season, Playoff, Toilet Bowl) count only what those players scored while this side owned them. Totals are per-side, not a zero-sum swing. Computed during refresh, cached incrementally, exposed on the trade detail response, and surfaced **inline in the trade journey** — each flipped asset's row expands to a linked "traded to *X* · *date* → became *[players]*" (replacing the old separate "Where it went" / "What it became" sections).

### Production timeline ("Did it pan out?")

The trade detail page charts each side's **cumulative production over the trade's tenure** (`web/components/ProductionTimeline.tsx`, inside `TradeProductionCard.tsx`). The chart is **chain-aware**: a received player's line runs while held, a **dropped** asset's line *stops* at the drop, and a **flipped** asset's line *continues* onto whatever the asset became (following the same lineage as the became grade). It runs on a calendar x-axis with season boundaries, overlays shaded bands for **playoff weeks** and **injury-OUT** stretches, and drops **departure markers** (named) where an asset was traded or cut. Built during refresh in `compute_production_series_payload`; the trade response carries `production_week_phases` and `departures`.

### Injury context

For each received player the refresh computes **games missed, split by season phase** (regular / playoff / toilet) plus current **live status**. The source is nflverse weekly rosters (`engine/injury_data.py`, fetched in `api/nflverse.py`); `engine/injury.py` classifies games-missed-by-phase and `engine/injury_live.py` derives the in-season badge. It is persisted on the cache and surfaced as the **Injury Impact** block and the timeline's OUT bands. A week counts as *played* only when the player actually **scored > 0** (IR players appear in the box score at 0.0, so presence alone would mask real injuries).

### Auto-refresh (Liveness)

The backend runs an in-process scheduler that periodically re-runs the refresh for every league it has already cached (the `chain_*.json` files), so caches stay warm and current. Page loads stay instant (they read the cache) and new trades appear automatically within the schedule interval, with no one having to trigger a manual refresh. It is incremental (a cycle that finds no new trades is nearly free) and best-effort (a league that fails is logged and skipped). Controlled by `TRADE_GRADER_AUTO_REFRESH` (default on) and `TRADE_GRADER_REFRESH_INTERVAL_SECONDS` (default 3 hours). The manual `GET /api/league/{id}/refresh` SSE endpoint still works for an immediate or forced refresh.

### Franchise Rating + the Franchise Ratings leaderboard

The **Franchise Ratings** tab (`/league/{id}/gm`) ranks every owner by a single league-relative grade — a transparent **two-pillar** composite (`0.60·Results + 0.40·Assets`, model `"v2_dynasty"`/`"v2_keeper"`; redraft scores **Results only**, model `"v2_redraft"`). This is v2 of the rating — the original three-pillar model had a **Skill** pillar (trade efficiency, draft skill, lineup skill) that measured noise: none of it persisted year to year (draft skill correlated ~+0.10 season to season, lineup skill ~+0.04, and both trade signals were *negatively* self-correlated). v2 drops Skill entirely and measures it through its consequences instead — winning, and what the roster holds:

- **Results** (60%) — **expected wins** (all-play win rate: your record if you'd played every team every week, which removes schedule luck), **playoff success** (a berth counts half a round win, plus rounds actually won, plus a championship bonus), and **luck** (actual wins minus expected wins, orthogonal to expected wins by construction).
- **Assets** (40%) — **roster value share**, **young-core share** (share of roster value held by players 25 and under — replaced a straight mean-age signal, which mostly measured bench filler), and **draft capital**. Dropped entirely for redraft (nothing carries over between seasons, so there's no subject to measure — Results is renormalized to 100%, not zeroed, since a zeroed pillar would still consume its weight and compress every grade toward 1500). Keeper drops young-core share (two or three keepers isn't a young roster) and renormalizes roster-value-share/draft-capital over the remaining weight.

Each signal is z-scored across the league, blended by weight into a pillar, and the pillars blend to a **1500-centered** number (clamped 800–2200) that is then mapped to a **letter grade** (`rating_to_letter`, A+ to D− with no F — a twelve-owner league spans roughly ±1.75 sd of composite, so an F band could only ever fire by construction or never fire at all). The **letter is a percentile within your league, not an absolute or cross-league scale** — the methodology page says so explicitly, and so should anyone describing it. Recency decay uses a **two-season half-life** (a chosen prior, not a measured one — not enough data exists to fit one), clamped so a season ahead of the anchor can't outweigh it. The band boundaries themselves lean on `REFERENCE_COMPOSITE_SD`, a **v1-era stand-in** carried forward until a live recalibration runs against the v2 composite — treat the bands as the mechanism, not a calibrated instrument, until that lands. The **letter is the face** everywhere; the number/rank/trend are the receipt. The live rating is assembled by `api/app/services/franchise_redesign.py::live_ratings` (single source of truth). The math is pure + unit-tested in `engine/gm_rating.py` (`compute_gm_ratings`, `rating_to_letter`, `V2_PILLAR_WEIGHTS`/`V2_SIGNAL_WEIGHTS`); signals are computed during refresh and persisted on the cache (SCHEMA_VERSION 17). `compute_gm_ratings` returns a full breakdown (pillar → signal → raw / z / weight / point contribution), so **every point is traceable**. Per-NFL-week rating snapshots (`rating_snapshot_store.py`) are stamped with the model that produced them, so a v1 rating can never be diffed against a v2 one; they drive the week-over-week **trend** arrow. There is no per-season rating under v2 — an all-time decayed tree can't produce one, and fabricating one would feed a false zero to the year-over-year delta and the Biggest Riser card, so `compute_season_ratings` returns `{}` and consumers fall back to their existing "no signal" path. The page also renders an Open Graph share card (`gm/opengraph-image.tsx`).

The retired v1 signals (`championships`, `made_playoffs`, `final_seed`, `points_for_rank`, `youth`, `roster_value`, `draft_skill`, `lineup_skill`, the trade signals) are **still persisted** on the cache — they no longer score the rating, but they still feed non-scoring consumers: the GM-blurb LLM facts packet (`blurb_gen.py`/`gm_rating_blurb.py` read `championships`/`made_playoffs` straight off `outcome_signals`) and the Outlook tab's draft-capital ranking (`outlook_build.py` reads `outlook_signals["draft_capital"]`).

### The draft board

Every draft class gets its own board at `/league/{id}/draft/{season}` — an owners rollup, the full picks ledger, and a "Going in" panel.

Each pick is measured against the **rookie consensus board as it stood on that draft's own date**, never today's, so a class can be assessed on draft night months before it plays: where the board had the player, where he actually went, and the gap between them. Owners are ranked by **Points Above Round** rather than raw points — raw points rank draft position, since whoever picks first tends to win, while Points Above Round is zero-sum within the class and rewards drafting well from a bad slot.

Once a class has played, each pick earns a **Hit / Average / Bust** verdict. There are no invented thresholds anywhere in it: a pick is a Hit if it beat three-quarters of the players ranked where it was ranked and held as long as it was held, a Bust if it fell below a quarter of them. Every bar is a percentile of what comparable picks really scored, priced in your league's own scoring — six-point passing touchdowns move a quarterback-heavy bar by about thirty points against four-point ones, so the history is stored as raw components and priced per league. Where a fair comparison can't be built, the column stays blank rather than guessing. Keepers are shown but never judged: a keep is not a draft decision.

The **Going in** panel reconstructs what each roster's starting lineup looked like when the draft opened — measured at the draft's *opening*, not its last pick, because a slow-clock rookie draft runs for days and the cuts managers make during it are them clearing room for the picks they're about to make, not holes they went in with. It reports which starting slots sat below replacement level in your league, and which of them the draft actually addressed. It's available for dynasty leagues with at least one prior season; keeper leagues are excluded, because the reconstruction can't model the annual release.

### Owner franchise page

Each owner has a **franchise identity page** (`/league/{id}/owner/{user_id}`, also the dashboard's Owners tab). It leads with a **verdict-and-rings hero** — the Franchise Rating letter, rank/trend, and a silverware strip (titles / playoff trips / career record / best finish) — then four tabs:

- **Overview — "Why this grade":** the pillars (Results, and Assets where the league carries one) and the signals inside them as diverging green/red contribution bars (points added to / subtracted from a league-average GM), each pillar carrying a one-line **LLM highlight**. This is the receipt for the ranking.
- **Track Record:** season-by-season finishes (champion / runner-up / playoff result / missed) from `season_records` (via `api/app/services/track_record_view.py`), plus an **all-time head-to-head** grid vs every league-mate (`engine/head_to_head.py` + `api/app/services/head_to_head_signals.py`, persisted as `head_to_head` on the cache).
- **Trades:** the five-metric totals, career arc, the "did your trades pan out?" production chart, and the full trade ledger.
- **Outlook:** roster health (age profile) + future/draft (pick arsenal, draft skill), ending with a **"How past picks panned out"** table — every rookie-draft pick with its value arc and five-metric production, a roster-status chip (rostered / traded / dropped), a games-started-for-owner count, a totals row, and an **All-Time** tab alongside the per-season views.

Owner names cross-link in from the Franchise Ratings rows and trade-detail pages. The per-pillar highlights reuse the GM-blurb pipeline (`GmRatingBlurbWriter` emits the paragraph + one highlight per scored pillar — Results, and Assets where present — in one Haiku call; surfaced as `franchise_rating.pillar_highlights`).

### Side bets

Alongside the graded trades, owners can track their own side action: manually recorded **1-vs-1 money bets** between two owners (e.g. "Tom finishes the regular season above Mike, $20"). Each bet carries a description, an amount, and a season, and moves through an **open → settled/push/void** lifecycle — settling picks a winner, a push returns no winner, and a void cancels the bet without deleting its record (the ledger is a receipt, not a todo list). The dashboard's **Bets tab** (`/league/{id}?tab=bets`) shows a per-owner leaderboard (won/lost/net, biggest win, worst loss) above the full ledger, with a form to record new bets and inline actions to settle/reopen/void each one; a compact **side-bets card** on the owner franchise page surfaces that owner's record. Bets are DB-backed (Postgres `side_bets` table, migration `0007`) rather than part of the league chain cache, so they never 409 on a cold cache — owner names degrade gracefully to raw Sleeper user IDs if the chain hasn't been pulled yet. Endpoints live under `/api/league/{league_id}/bets` (see the API table below).

### Draft grading

Every league's yearly draft is graded, in all three formats. Dynasty grades rookie classes; **redraft and keeper grade every season's full draft, including year one**. Selection reads Sleeper's `settings.player_type`, but only as one signal — it restricts the selectable *pool*, it does not name the kind of draft, so an open-pool draft outside the league's first season is a rookie draft, not a startup.

Grading runs on **three independent baselines, never blended**: a league-native peer delta (each pick against the same round/tier of its own draft — under v2 this feeds the owner page's standalone draft-skill display, not the Franchise Rating, which dropped its Skill pillar entirely), an **ADP delta**, and a **projection delta**. ADP and projected points both come from Sleeper's own projections endpoint, keyed by native player id, covering K and DEF.

**ADP is pinned to each draft's own date.** A dated snapshot of the whole market is captured daily, and each draft resolves against the snapshot on-or-before its own `last_picked` — never after. A league drafting Aug 1 and one drafting Aug 26 face different markets and are graded against their own. Grading against live ADP would be grading against hindsight, so ADP works **going forward only**: a draft predating the first daily snapshot has no baseline and grades on the peer baseline alone.

Keeper picks are shown but never scored, and auction drafts are ingested but never graded (their pick order is the order money changed hands). **Results and grades have different availability dates** — a class that has completed but not played reports its results with grading withheld, so the board is useful on draft night.

Surfaces: a league-wide board at `/league/{id}/draft/{season}`, a **Draft** tab on each owner page, and the draft-window dashboard lead.

### Admin & product telemetry

The `/admin` surface (gated to `TRADE_GRADER_ADMIN_EMAILS` users) shows users, leagues, LLM spend + a budget editor, and **product telemetry**. A client beacon posts each route change to `POST /api/events` (user-scoped, query strings stripped) into a `page_events` table; the admin views then surface **active users** (DAU/7d/30d), **per-league activity**, and a **per-user activity drill-down** (`/admin/user/{id}`). User **engagement** is tracked as distinct active days (`users.active_days` / `last_active_at`, stamped once per user per UTC day). No extra config — telemetry uses the existing identity DB and migrations.

**Admin support access.** An admin may open any league, including ones they hold no membership row for, so a reported bug can be reproduced and another league's setup can be inspected. It is **read-only**: `GET`/`HEAD` bypass the membership check, writes still `403`. `/refresh` is a `GET`, so warming a cold cache to reproduce something still works. Every league route carries a banner while you are in a league that is not yours, so someone else's numbers are never mistaken for your own. There is deliberately **no audit trail** — fine at one admin, worth revisiting before granting `is_admin` to a second person.

### Backups and restore

The backend runs a **daily in-process job** (`api/app/services/backup_service.py`, started in `main.py`'s lifespan) that backs up both state stores — Postgres (identity, memberships, side bets, app settings, page events) and the `TRADE_GRADER_CACHE_DIR` cache volume (the `ChainCache`, KTC/ADP snapshots) — to a Cloudflare R2 bucket. It is **catch-up scheduled**: rather than sleeping to a fixed instant, each cycle asks "is today already backed up, and are we past `TRADE_GRADER_BACKUP_HOUR_UTC`?", so a redeploy that lands after the target hour still runs that day's backup instead of skipping it.

**What is backed up:**
- **Postgres** is dumped *logically* through SQLAlchemy reflection, not `pg_dump` — the schema is a handful of tables of plain scalars, so a binary dump buys no fidelity, and reflection lets the same code path run against the SQLite dev database too (which is what makes restores rehearsable without a Postgres instance). Written as gzipped JSONL, one row per line, in FK-dependency (`sorted_tables`) order. `_encode`/`_decode` round-trip `String`/`Integer`/`Boolean`/`Date`/`DateTime` only — `test_backup_dump.py::test_every_column_type_is_dumpable` fails the build the moment a migration adds a column type outside that set (e.g. JSONB, bytea), so a silent lossy backup can't ship unnoticed.
- **The cache volume** is tarred (`.tar.gz`) whole. In-flight `write_json_atomic` temp files (`.*.tmp`) are skipped — they're a concurrent writer's private, guaranteed-partial state.

**Object layout**, one run per day under a timestamped prefix:

```
backups/<run-id>/postgres.jsonl.gz   # gzipped JSONL, one row per line
backups/<run-id>/cache.tar.gz        # the whole cache volume
backups/<run-id>/manifest.json       # written LAST — the run's commit marker
```

`<run-id>` is `YYYY-MM-DDTHH-MM-SSZ`. **`manifest.json` is uploaded last on purpose** — it's the receipt a restore checks itself against (per-table row counts, cache member count/bytes, the Alembic revision, the `ChainCacheEntry.SCHEMA_VERSION`, the deployed git SHA), and a prefix without one is a run that died partway through. `scripts/restore.py::pick_latest_run` skips any such prefix rather than silently restoring half a database.

**Two-token split.** The app's R2 credentials (`TRADE_GRADER_R2_ACCESS_KEY_ID`/`SECRET`) are **Object Read & Write**; restoring uses a **separate, Object-Read-only** token, supplied only to `scripts/restore.py` via `R2_READ_ACCESS_KEY_ID`/`R2_READ_SECRET_ACCESS_KEY` and never given to the running app.

**What that token can and cannot do — stated honestly.** `api/app/services/r2.py` is the one module that knows R2 exists and it has **no `delete` and no `list` call at all**, and must not gain one. That is hygiene, and it is worth stating: the app cannot erase or enumerate backup history by accident. It is **not an access control** — an attacker holding the credential does not run our code. R2 offers no put-only permission group (the token UI has Admin Read & Write / Object Read & Write / Object Read only), so the narrowest write-capable credential that can actually be created **can delete and overwrite**. The controls that genuinely protect backup history are therefore:

- **A bucket lock rule** (required setup step below). Note that **R2 does not support object versioning** — it is a standing feature request, not a shipped feature, so the usual "an overwrite leaves the prior version recoverable" answer is unavailable here. Bucket locks are the substitute and are in fact stronger: they prevent deletion *and* overwriting of objects under a prefix for a retention period, and **lock rules take precedence over lifecycle rules**, so a locked object cannot be reaped early. Even a hypothetical put-only token could overwrite an existing key, so the lock is the load-bearing control either way.
- **The lifecycle rule** for retention.

The timestamped run prefixes do make a *blind* overwrite hard for something that cannot list — it would have to guess a run id — but that is an obstacle, not a guarantee.

**Retention** is a Cloudflare **bucket lifecycle rule** (delete under `backups/` after 30 days) — configured in the R2 dashboard, never in app code.

**Failure visibility:** every run's outcome — last success time, last error, last run id — is persisted to `app_settings` (`record_status`) and surfaced on `/admin` so a silently-broken backup is caught there instead of at restore time.

**Restoring** (`scripts/restore.py`) runs from an operator machine, never the app:

```bash
python scripts/restore.py \
  --database-url postgresql+asyncpg://localhost:5433/scratch \
  --cache-dir /tmp/restored-cache
```

It selects the newest complete run by default (`--run <run-id>` to pick a specific one), runs `alembic upgrade head` against the target, restores both stores, verifies the restored row/file counts and the tarball's byte size against the manifest, and refuses to touch a `--database-url` that looks like production (`rlwy.net`/`railway.internal`) unless `--allow-production` is passed explicitly. Three more preflights refuse rather than half-restore: a **non-empty target database** (named table + row count — restore inserts, it does not merge), a **schema drift** between the manifest's `alembic_revision` and where `alembic upgrade head` left the target (override with `--allow-schema-drift` once you have confirmed the intervening migrations are additive), and any **unsafe tar member** (`safe_extract` rejects anything that is not a regular file, and any absolute or `..`-bearing name, then extracts only that vetted list).

**Verified end to end 2026-08-13.** The first production backup (`2026-08-13T19-08-45Z`) was restored into a scratch Postgres 18.4 — the same minor version as production — and the API was booted against the restored state. What that proved, beyond what the offline tests cover:

- **The R2 path works.** SigV4 against `<account>.r2.cloudflarestorage.com`, and the `request_checksum_calculation="when_required"` pin that keeps botocore from sending `aws-chunked` trailers a non-AWS endpoint may reject.
- **Real Postgres round-trips exactly.** `md5(string_agg(...))` over whole tables matched prod for `users`, `league_memberships` and `side_bets`; `timestamptz` values matched to the microsecond, which the SQLite-based offline test structurally cannot show (it compares naive to naive). The two tables that differed were explained drift, not corruption: `app_settings` (the three `backup.*` status rows are written *after* the dump) and `page_events` (one new row since; the oldest 341 hashed identical).
- **Both stores came back usable.** All three leagues' `ChainCache` entries deserialized at schema v16 with 86 cached LLM trade stories intact; the dashboard returned 200 rather than `409 cache cold`, the bet ledger returned its 3 rows, and a trade detail rendered its stored verdict and body.

One near-miss worth recording: the first scratch container silently failed to bind its port, and `localhost:5433` was answered by an *unrelated project's* Postgres. The restore aimed at it and was stopped by the database-emptiness preflight before `alembic upgrade head` could run. Point restores at a port you have just verified with `docker ps`.

**Live configuration (as of 2026-08-13).** Bucket `public-dynasty-backup`, backups daily at 09:00 UTC. Both guard rails are in place, each scoped to prefix `backups/`: a **bucket lock rule** with 30-day retention, and an **object lifecycle rule** deleting after 30 days. Note these are two separate entries in the bucket's Settings sidebar, not one — a lock rule is not a lifecycle rule.

**Operator runbook — configuring R2** (kept for rebuilding this from scratch; all steps are manual, since an agent session has no Cloudflare dashboard):

1. In the Cloudflare dashboard, create (or confirm) two API tokens scoped to the bucket: one **Object Read & Write** for the app, one **Object Read** for restores. (There is no put-only option — see the token discussion above for what that credential can actually do.)
2. Add a **bucket lock rule** (Settings → Bucket Lock Rules) covering prefix `backups/` with a **30-day** retention, matching the lifecycle rule below. This is required, not optional: it is the control that makes the app's credential unable to erase backup history, and that credential can delete and overwrite. Because lock rules beat lifecycle rules, the object survives its full 30 days and is then reaped — nothing is retained forever. **Do this after the first successful dry run**, not before: a lock applies to existing objects too, so locking an unverified pipeline's output means living with it for 30 days.
3. Add a bucket **lifecycle rule** deleting objects under `backups/` after 30 days.
4. Set the Railway variables on the `api` service (see the `railway-deploy` skill; confirm `railway status` first):

   ```bash
   railway variables --service API \
     --set TRADE_GRADER_BACKUP_ENABLED=true \
     --set TRADE_GRADER_BACKUP_HOUR_UTC=9 \
     --set TRADE_GRADER_R2_ACCOUNT_ID=<account-id> \
     --set TRADE_GRADER_R2_BUCKET=<bucket> \
     --set TRADE_GRADER_R2_ACCESS_KEY_ID=<key> \
     --set TRADE_GRADER_R2_SECRET_ACCESS_KEY=<secret>
   ```

5. Push to `main` (auto-deploys), then confirm in the logs: `railway logs --service API | grep -i backup` should show `backup scheduler started (daily at 09:00 UTC)`.
6. Wait for (or catch-up-trigger) the first run, confirm `/admin` shows a `last_ok_at`, then restore it into scratch targets. `scripts/` is **not** copied into the api image, so the restore runs from a repo checkout and needs the engine, the backend and boto3 importable there first:

   ```bash
   pip install -e . && pip install -e ./api && pip install 'boto3>=1.35'

   docker run -d --name scratch-pg -e POSTGRES_PASSWORD=scratch -p 5433:5432 postgres:18
   export R2_ACCOUNT_ID=<account-id> R2_BUCKET=<bucket>
   export R2_READ_ACCESS_KEY_ID=<read-key> R2_READ_SECRET_ACCESS_KEY=<read-secret>

   python scripts/restore.py \
     --database-url postgresql+asyncpg://postgres:scratch@localhost:5433/postgres \
     --cache-dir /tmp/restored-cache
   ```

   Expect `database OK`, `cache OK`, `restore complete`. Then boot the API against the restored state:

   ```bash
   TRADE_GRADER_DATABASE_URL=postgresql+asyncpg://postgres:scratch@localhost:5433/postgres \
   TRADE_GRADER_CACHE_DIR=/tmp/restored-cache \
   TRADE_GRADER_AUTO_REFRESH=false \
   TRADE_GRADER_BACKUP_ENABLED=false \
   make dev-api
   ```

   and verify the league dashboard renders **without** `409 cache cold`, the side-bet ledger shows its rows, and an owner page shows a cached trade story — those three together prove both stores actually came back (a cold dashboard means the tarball didn't restore; missing bets mean the database didn't).
7. Tear down: `docker rm -f scratch-pg && rm -rf /tmp/restored-cache`.

### API endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET`  | `/api/health` | Liveness check. |
| `POST` | `/api/lookup` | `{ username }` → the user's dynasty leagues. |
| `GET`  | `/api/league/{league_id}` | Dashboard payload. Query: `year` (`all` or a season int), `lens` (`ktc` \| `production`) — drives the hero-card verdict only. `409` if cache cold. |
| `GET`  | `/api/league/{league_id}/refresh` | **SSE** stream — pulls + grades the chain, emits `progress`/`done`/`error` events, persists to cache. |
| `GET`  | `/api/league/{league_id}/owner/{user_id}` | Per-owner franchise page (Franchise Rating + pillar highlights, Track Record, head-to-head, trades, outlook). |
| `GET`  | `/api/league/{league_id}/trade/{trade_id}` | Per-trade detail (direct grade, LLM story, and the "became" grade). |
| `GET`  | `/api/league/{league_id}/leaderboard` | Franchise Ratings leaderboard (letter + composite rating + pillar / per-signal breakdown + week-over-week trend). Query: `year` (`all` or a season int; v2 ratings are all-time only, so this scopes the display rows, not the rating itself). `409` if cache cold. |
| `GET`  | `/api/league/{league_id}/bets` | List side bets. Query: `owner_id`, `season`. Never 409s (DB-backed). |
| `POST` | `/api/league/{league_id}/bets` | Record a new side bet. |
| `PATCH` | `/api/league/{league_id}/bets/{bet_id}` | Edit an open bet, or change its status (settle/push/void/reopen). |
| `GET`  | `/api/league/{league_id}/bets/summary` | Per-owner won/lost/net rollups. Query: `season`. |
| `GET`  | `/api/league/{league_id}/draft/{season}` | League-wide draft board for one class — every owner's picks in draft order, plus a per-owner summary. `409` if cache cold; `404` names the seasons that do exist. |

---

## Configuration

### Backend (env, prefix `TRADE_GRADER_`, also reads `api/.env`)

| Var | Default | Notes |
|---|---|---|
| `TRADE_GRADER_CACHE_DIR` | `~/.sleeper-dynasty/cache` | Set to the mounted volume in prod (`/data/sleeper-dynasty/cache`). |
| `TRADE_GRADER_CORS_ORIGINS` | `["http://localhost:3000"]` | Allowed web origins. |
| `TRADE_GRADER_CHAIN_CACHE_TTL_SECONDS` | `86400` | Chain-cache TTL. |
| `TRADE_GRADER_LOG_LEVEL` | `INFO` | |
| `PORT` | `8000` | Provided by Railway in prod. |
| `ANTHROPIC_API_KEY` | _(unset)_ | Required to generate trade stories during refresh. If absent, stories are skipped with a warning. |
| `TRADE_GRADER_AUTO_REFRESH` | `true` | In-process scheduler that keeps cached leagues warm. Set `false` to disable. |
| `TRADE_GRADER_REFRESH_INTERVAL_SECONDS` | `10800` | Auto-refresh interval (default 3 hours). |
| `TRADE_GRADER_LLM_MIN_INTERVAL_SECONDS` | `72000` | Minimum gap between LLM prose passes (default 20 hours; `0` disables the time throttle). The offseason gate skips prose regeneration independently of this. |
| `TRADE_GRADER_AUTH_BACKEND_SECRET` | _(unset)_ | Shared HS256 secret the backend uses to verify the token minted by the web app. **Must equal the web `AUTH_BACKEND_SECRET`.** Without it every authenticated request 401s. |
| `TRADE_GRADER_DATABASE_URL` | SQLite under cache dir | Identity DB (users, league memberships, sessions). Prod uses managed Postgres (`postgresql://…`, auto-normalized to `asyncpg`); unset falls back to a SQLite file. |
| `TRADE_GRADER_ADMIN_EMAILS` | _(unset)_ | Comma-separated emails granted `is_admin` on upsert (admin-only routes/UI). |
| `TRADE_GRADER_ALLOWLISTED_LEAGUE_ID` | _(unset)_ | Rollout bridge: signed-in users may view this one league without a membership row. |
| `TRADE_GRADER_SENTRY_DSN` | _(unset)_ | Sentry error monitoring. When set, the backend initializes Sentry (auto-instruments FastAPI). Inert if unset. |
| `TRADE_GRADER_BACKUP_ENABLED` | `false` | Turns on the daily R2 backup scheduler. Also requires the four R2 vars below (`backup_configured`) or the scheduler stays idle. |
| `TRADE_GRADER_BACKUP_HOUR_UTC` | `9` | UTC hour the daily backup runs at (catch-up scheduled — see Backups and restore above). |
| `TRADE_GRADER_R2_ACCOUNT_ID` | _(unset)_ | Cloudflare account id for the R2 endpoint. |
| `TRADE_GRADER_R2_BUCKET` | _(unset)_ | R2 bucket name backups are written to. |
| `TRADE_GRADER_R2_ACCESS_KEY_ID` / `TRADE_GRADER_R2_SECRET_ACCESS_KEY` | _(unset)_ | **Object Read & Write** token for the app (R2 has no put-only option — a bucket lock rule is what protects history; R2 has no object versioning). Restoring needs a separate Object-Read token supplied to `scripts/restore.py`, never this one. |

### Frontend (env)

| Var | Default | Notes |
|---|---|---|
| `API_URL` | `http://localhost:8000` | Backend base URL for the server-side proxy + RSC fetches. Baked at **build** time. |
| `AUTH_SECRET` | _(unset)_ | NextAuth session/JWT signing secret. Required in prod. |
| `AUTH_GOOGLE_ID` / `AUTH_GOOGLE_SECRET` | _(unset)_ | Google OAuth client credentials (the only sign-in provider). |
| `AUTH_BACKEND_SECRET` | _(unset)_ | HS256 secret used to mint the backend-facing token. **Must equal the API's `TRADE_GRADER_AUTH_BACKEND_SECRET`.** |
| `AUTH_TRUST_HOST` | _(unset)_ | Set `true` behind a proxy (Railway) so NextAuth builds callback URLs from the request host. |
| `AUTH_URL` | _(unset)_ | Canonical site URL for OAuth, e.g. `https://dynasty.tomkeefe.ai`. The Google client must list `<AUTH_URL>/api/auth/callback/google` as an authorized redirect URI. |
| `CANONICAL_HOST` | _(unset)_ | When set (e.g. `dynasty.tomkeefe.ai`), middleware 308-redirects any other host to it. Inert if unset. |
| `SENTRY_DSN` / `NEXT_PUBLIC_SENTRY_DSN` | _(unset)_ | Sentry error monitoring (server/edge and browser respectively). Each `Sentry.init` is gated on its DSN; inert if unset. `NEXT_PUBLIC_` reaches the client bundle. |
| `LEAGUE_ID` | _(unset)_ | Legacy single-tenant league id. The app is now multi-tenant + login-gated: `/` is the "My Leagues" home, and unauthenticated visitors are redirected to `/login`. Local dev: `web/.env.local`. |
| `PORT` | `3000` | |

### CLI (env)

| Var | Used by | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | `recap` | Required to generate the recap narrative. |

---

## Testing

```bash
make test        # backend + frontend unit tests
make test-api    # cd api && pytest -v
make test-web    # cd web && npm run test -- --run

cd web && npm run test:e2e   # Playwright smoke tests
pytest -v                     # engine/CLI suite (from repo root)
```

---

## Deployment (Railway)

Three services in one Railway project — two app services (each built from its own Dockerfile, `railway.json` sets `builder: DOCKERFILE`) plus a managed Postgres:

- **Backend** (`api/Dockerfile`) — installs the engine + API, runs `uvicorn` on `$PORT` (bound to `::` for Railway's IPv6 private network). Mount a **persistent volume** at `/data/sleeper-dynasty/cache` so the `ChainCache` survives deploys (`TRADE_GRADER_CACHE_DIR` already points there in the image).
- **Frontend** (`web/Dockerfile`) — multi-stage build producing Next.js `standalone` output, runs `node server.js` on `$PORT`. Set `API_URL` to the backend service's internal URL (baked at build time).
- **Postgres** (managed) — identity store (users, league memberships, sessions). Point the backend at it via `TRADE_GRADER_DATABASE_URL` (e.g. `${{Postgres.DATABASE_URL}}`).

```bash
make build   # build both app images locally to verify Dockerfiles
```

Auth/config checklist for a fresh deploy:

- Set the **same** secret on both sides: web `AUTH_BACKEND_SECRET` == api `TRADE_GRADER_AUTH_BACKEND_SECRET` (mismatch → every authenticated request 401s).
- Set web `AUTH_SECRET`, `AUTH_GOOGLE_ID`/`AUTH_GOOGLE_SECRET`, `AUTH_TRUST_HOST=true`, and `AUTH_URL` to the public origin.
- In the Google OAuth client, authorize `<AUTH_URL>/api/auth/callback/google` as a redirect URI (one per domain you serve).
- Point the backend at Postgres via `TRADE_GRADER_DATABASE_URL`.
- Set CORS on the backend (`TRADE_GRADER_CORS_ORIGINS`) to the deployed frontend origin.

Both app services **auto-deploy on push to `main`** via Railway's native GitHub integration (no GitHub Actions workflow). `railway up --service <api|web>` is the manual fallback.
