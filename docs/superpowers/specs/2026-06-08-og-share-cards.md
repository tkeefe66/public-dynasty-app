# OG Share Cards — Design Spec

**Date:** 2026-06-08
**Epic:** Distribution (#1 of the roadmap: Distribution → Lineage → Narrative → Liveness)
**Status:** Design — pending user review before implementation plan

## Problem

PRODUCT.md's success metric is "an argument in the group chat ends with someone
pasting a link to this tool." Today pasting a link drops a **bare URL** — no
preview, no verdict, no numbers (`ShareUrlButton` just copies
`window.location.href`, and there is no `generateMetadata`/OG anywhere in `web`).
The moment that should settle the argument falls flat.

## Goal

When anyone pastes a trade, owner, or league link into iMessage, Telegram,
Discord, Slack, etc., it **unfurls into a rich card** showing the verdict and the
receipts. Purely passive: no bot, no buttons, no integration. It works
everywhere link previews work, and it makes everything already built more
shareable. (It also leaves the cards ready for a future Telegram/Discord
auto-post epic.)

## Decisions locked during brainstorming

| Decision | Choice |
|---|---|
| Scope | **Option A: rich unfurls only.** No share buttons, no Telegram/Discord push this cycle. |
| Surfaces | **All three:** trade detail, owner page, league home. |
| Card style | **C: box score** — a short verdict/headline strip on top, then the metrics as a mini scoreboard, plus a footer mark. Owner + league cards adopt the same look. |
| Generation | **Next.js App Router dynamic OG** via `next/og` `ImageResponse`, rendered per-request. No storage, no external service. |

## Why dynamic next/og (not alternatives)

- **Dynamic `opengraph-image.tsx`** is the native Next 14 App Router mechanism;
  it re-renders whenever the underlying data changes, needs no storage, and
  reuses the data fetchers the pages already use.
- *Rejected:* pre-rendering static PNGs during refresh (storage + regeneration
  complexity, no benefit at ~10 owners / dozens of trades); third-party OG image
  services (`next/og` is built in).

## Architecture

Three image routes + three `generateMetadata` exports + one shared template.

```
web/
  lib/
    og-card.tsx          # shared box-score card template (returns JSX for ImageResponse)
    og-runtime.ts        # font loading + size/runtime constants (1200x630, nodejs)
  app/league/[id]/
    opengraph-image.tsx                 # league card
    owner/[uid]/opengraph-image.tsx     # owner card
    trade/[tid]/opengraph-image.tsx     # trade card
    (page.tsx files gain generateMetadata)
```

- Each `opengraph-image.tsx`:
  - `export const runtime = "nodejs"` and `export const size = { width: 1200, height: 630 }`, `export const contentType = "image/png"`.
  - Fetches its data with the **existing** `lib/api` fetchers (`tradeDetail`,
    `ownerDetail`, `dashboard`) — the same calls the page components already make
    server-side.
  - Maps the data to card props and returns `new ImageResponse(<OgCard .../>, {...size, fonts})`.
- `lib/og-card.tsx` exports a single `OgCard` layout function parameterized by a
  discriminated union (`{kind: "trade" | "owner" | "league", ...}`) so all three
  surfaces share the header-strip / scoreboard / footer-mark system. Satori (the
  renderer behind `ImageResponse`) supports a flexbox subset; the template uses
  only flexbox + absolute positioning, no external CSS.
- `generateMetadata` on each page sets `title`, `description`,
  `openGraph.images` (pointing at the route's own `opengraph-image`), and
  `twitter.card = "summary_large_image"`. (Next auto-wires `opengraph-image.tsx`
  into the page's OG image tags, but we set `title`/`description` explicitly.)

### Fonts

`ImageResponse` needs explicit font data (it cannot use system fonts). Bundle a
small set under `web/assets/fonts/`: a sans in two weights (e.g. Inter Regular +
SemiBold) for headings/values and one monospace (e.g. a mono for the eyebrow
labels and figures, matching the app's `tabular`/mono accents). `og-runtime.ts`
reads them with `fs.readFile` (nodejs runtime) once and passes them to every
`ImageResponse`.

### Avatars

Cards use **initial-based avatars** (a colored circle with the owner's first
letter), not the remote Sleeper avatar URLs. Satori can fetch remote images but
that adds latency and a failure mode; initials are reliable and match the
mockups. (If we later want real avatars, it's a contained upgrade.)

## Card content (box-score template)

All cards: 1200×630, dark background (`#0d0e10`), app tokens (ink `#e8eaed`, dim
`#8b9096`, pos `#3fb950`, neg `#f85149`), a `sleeper·dynasty` footer mark, and a
mono eyebrow with league + season context.

**Trade card** (`trade/[tid]`)
- Header: the stored **verdict** (`data.story.verdict`), one line, font-size
  clamped to fit (it is a single sentence). Fallback when `story` is null:
  `"{ownerA} ↔ {ownerB}"`.
- Scoreboard (the **winner's** column tinted; winner = the side with the larger
  Trade Value swing, i.e. the positive `snapshot_ktc_swing`; "too close" if the
  swing rounds to 0): **Trade Value**
  (`snapshot_ktc_swing`), **Total Points** (`hindsight_production_swing`),
  **Playoff Points** (`hindsight_started_playoff_swing`), each shown +/− per
  owner.
- Asset line: "{ownerA} got {assets_short_a} · {ownerB} got {assets_short_b}"
  (built from `sides[].received` names, truncated).
- Eyebrow: "{league_name} · {season} · {seasonWeekLabel(date, week)}".

**Owner card** (`owner/[uid]`)
- Header: owner name + initial avatar.
- Headline: net **Trade Value** (`totals_by_lens.ktc`), colored.
- Row: Net Trade Value / Total Points (`totals_by_lens.production`) / Trades
  (count from `career_arc`).
- "Biggest heist" + "Biggest blunder": resolve `best_trade_id` /
  `worst_trade_id` to a one-line label (counterparty + swing). (Data already on
  `OwnerDetailResp`.)
- Eyebrow: "{league_name} · career".

**League card** (`league/[id]`)
- Header: league name + season.
- Subhead: "{N} managers · {M} trades graded".
- Standings top-3 by net Trade Value (rank, owner, net value) from
  `dashboard().standings`.
- Eyebrow: "DyNASTY · trade grader".

## Metadata text

- Trade: `title` = the verdict (or "{A} ↔ {B}"); `description` =
  "{league} · {season}: {short swing summary}".
- Owner: `title` = "{owner} — {net trade value}"; `description` = career one-liner.
- League: `title` = "{league} · {season}"; `description` = "{N} managers, {M}
  trades graded."

## Error & edge handling

- The image route must **never throw an unfurl-breaking error**. If a fetcher
  returns `409 cache cold` or any error, render a **generic branded fallback
  card** (league name if known, else "DyNASTY · trade grader") so the preview
  still looks intentional. The cold-start contract is unchanged; a not-yet-graded
  league simply shows the fallback until refreshed.
- Long verdicts: clamp font-size by length (buckets) so the headline always
  fits 1200px without overflow.
- `generateMetadata` mirrors the same fallback (never throw).

## Testing

- **Unit:** the data→card-props mapping per surface (`lib/og-card` mappers):
  correct winner tint, correct +/− metric values, asset-line truncation, the
  null-story fallback, the cold-cache fallback. Pure functions, vitest.
- **Render smoke:** a test that calls each `opengraph-image` handler with mocked
  fetchers and asserts it returns an `ImageResponse` (HTTP 200, `image/png`) and
  does not throw on the cold-cache path.
- **Manual:** render each route locally (`/league/.../trade/.../opengraph-image`)
  and eyeball the PNG; validate the live unfurl with an OG debugger
  (opengraph.xyz) and a real paste into iMessage + Telegram.

## Deployment / config

- The web service is a Next **standalone** Docker image on Railway, so the OG
  routes use `runtime = "nodejs"` (edge runtime is not available standalone).
  Confirm the bundled font files are included in the standalone output (they are
  read via `fs` from `web/assets/fonts/`, which the Dockerfile must COPY into the
  runner stage).
- No new env vars. The OG routes use the same `API_URL` the pages use.

## Out of scope (this cycle)

- Telegram/Discord auto-post and "share to chat" buttons (later Distribution
  follow-on, and depends on epic #4 new-trade detection for auto).
- Real (remote) Sleeper avatars on cards.
- Per-season or filtered share cards.

## Open questions

None blocking. Font choice and the exact verdict-clamp buckets are tuned during
implementation.
