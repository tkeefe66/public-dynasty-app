---
name: og-card-satori-gotchas
description: Use when touching web/lib/og-card.tsx, web/lib/og-card-data.ts, web/lib/og-font.ts, or any web/app/**/opengraph-image.tsx route, or writing any Satori / next/og / ImageResponse code, or adding a new share card or social preview — and when an OG route 500s, a card renders blank / misaligned / with columns collapsed, a font silently falls back to a default, or an unfurled link shows the fallback card instead of real data.
---

# OG cards with Satori in this repo

Satori is not a browser. It parses your style objects with a strict, tiny CSS
subset and throws on things a browser would ignore. Everything below cost
someone a debugging session here — none of it is generic Satori documentation.

Files: `web/lib/og-card-data.ts` (pure data), `web/lib/og-card.tsx` (renderers),
`web/lib/og-font.ts` (fonts), four routes under `web/app/league/[id]/**/opengraph-image.tsx`.

## The four hard constraints

### 1. A style value that is `undefined` throws — it is not ignored

Satori's style parser calls `.trim()` on every *declared* value, including ones
you set to `undefined`. One conditional prop takes down the whole render with a
`.trim is not a function`-class error, not just that declaration.

```tsx
// ❌ throws when borderTop is false
<div style={{ borderTop: borderTop ? `2px solid ${C.ink}` : undefined }} />

// ✅ spread the whole declaration in, or leave it out entirely
<div style={{ ...(borderTop ? { borderTop: `2px solid ${C.ink}` } : {}) }} />
```

Conditional styles must resolve to a concrete value or be **absent from the
object**. Never pass an optional style value down through a component prop —
`og-card.tsx`'s `HeaderLabel` deliberately has **no** `align`/`textAlign` prop
for exactly this reason (see its comment at `og-card.tsx:133`); alignment is the
parent `Cell`'s `justifyContent` job.

### 2. Flexbox only — no grid, no repeating gradients

The app's ledger is `display: grid` (`globals.css`'s `.ruled > *`) over a
`repeating-linear-gradient` ground. **Neither ports.** The card rebuilds the
same look as flex cells at fixed pixel widths (`Cell`, `Row` in `og-card.tsx`),
and paints each row as a flat `--rule-lit` background with an explicit
`borderBottom` hairline — the ground *is* the divider.

Give every container `display: "flex"` explicitly. Column widths are literal
numbers (`width={192}`), one flexible cell (`width="flex"` → `flex: 1,
minWidth: 0`); `Cell` sets `overflow: "hidden"` so a long name clips instead of
pushing the figure column off-canvas.

### 3. Fonts are fetched over HTTP at render time, never read off disk

`web/next.config` builds `output: "standalone"`, which prunes `node_modules` to
what Next's build-time import tracing can see. A runtime `fs.readFile` of a
binary font with no accompanying `import` is exactly the reference shape tracing
misses — it works locally and 500s in the Railway image. `og-font.ts` fetches
instead:

- **Bricolage Grotesque 800/700** (`DISPLAY_FAMILY`, matching `--weight-display`
  / `--weight-heading`) — Google Fonts CSS with a non-woff2 `User-Agent`, then
  `extractFontUrl` pulls the `.ttf` out. Satori needs TTF/OTF/WOFF; **WOFF2 is
  not supported**, and the default UA gets you WOFF2. Archivo 900 is retired
  along with Agate, so the old 900 sites are 800 — Bricolage's axis stops there.

  **This is why the card cannot read `.design/assets/fonts/`, even though those
  are the app's real self-hosted faces:** all six builds are woff2 (`wOF2`), and
  next/og's bundled parser has no woff2 decoder — `grep -c woff2` over
  `node_modules/next/dist/compiled/@vercel/og/index.node.js` is **0**. The
  standalone-tracing problem below is the *second*, independent reason. Cost of
  the workaround: the card renders static cuts, so Bricolage's `opsz` axis does
  not follow its 68–88px nameplates. Fixing that needs a build-step woff2→TTF
  conversion committed outside `.design/`.
- **Geist Mono 400/700** — not on Google Fonts (the app gets it from the `geist`
  npm package), so it comes from jsdelivr's npm mirror pinned by
  `GEIST_VERSION`.

`GEIST_VERSION` is a hand-maintained constant and `package.json` pins `geist`
with a **caret**. Bumping only `package.json` fails nothing and silently keeps
serving the old version's TTF. `web/tests/og-font.test.ts` asserts the literal
jsdelivr URL, so bumping only the constant turns that test red — the test guards
the constant, never the drift. Move `package.json`, `GEIST_VERSION`, and that
test together, and `curl -I` the new jsdelivr path before trusting it — a minor
bump can move `dist/fonts/geist-mono/`. The asymmetry that hides this: the app's
own faces come from the installed package (`geist/font` in `web/app/layout.tsx`)
and update with `npm install`; only the card's copy is hand-pinned.

**Every `(fontFamily, fontWeight)` pair a style uses must be registered in
`loadFonts()`.** An unregistered pair does not error — Satori substitutes, so the
symptom is "right numbers, wrong face," never a stack trace. `loadFonts()`
registers four pairs: Bricolage Grotesque 800, Bricolage Grotesque 700, Geist Mono
400, Geist Mono 700, exported as `REGISTERED_FONTS`. `tests/og-font.test.ts` greps
`og-card.tsx` for every `fontFamily`/`fontWeight` pair and fails if one has no
registered face, so adding a weight to a style without adding it to `loadFonts()`
now goes red. (The display 700 was genuinely missing once — three call sites
silently rendered on the heavier cut — which is why that test exists.)

That test is also the only thing that catches a family **rename**: og-font.ts and
og-card.tsx's eight `fontFamily` strings must move in the **same commit**, or
every card renders in a substituted face with no error anywhere.

`loadFonts()` memoizes into a module-level `cached` for the process lifetime: a
font change needs a **process restart**, not a page reload. It is also four live
network calls on every cold start. Every fetch goes through `fetchBytes`, which
checks `r.ok` and throws `<what>: <status> from <url>` — without that a 404 or
5xx hands Satori a chunk of HTML as font bytes and surfaces as an opaque throw
inside the font parser rather than "the CDN is down." `extractFontUrl` returning
null throws `no ttf for <family> <weight>`, which is what you'll see if Google
ever changes its CSS response shape.

### 4. Satori cannot read CSS custom properties

`var(--ink)` resolves to nothing, so `og-card.tsx`'s `C` object inlines hex
literals. **`C` is now STALE and known to be:** it still holds the retired Agate
light values (`#f7f6f1` bg, `#141312` ink), while the app renders Furniture
(`#f4f3ef`, `#14151a`, cobalt). Nothing enforces the match and `globals.css` no
longer holds a value to copy — re-sync `C` against `.design/tokens/colors.css`'s
`:root` when the cards get their colour port. Type is already ported; colour is not.
The drift guard's `raw-hex` rule excepts this file for exactly this reason.

Cards ship **light-only** and deliberately: group chats and Sleeper are dark, so
newsprint is what gets noticed (`design_handoff_agate/DESIGN.md:144`). There is
no dark card. Do not add a `prefers-color-scheme` branch.

## The canvas: 1200×630, 52px pitch

"The Card Is The Ledger" — the same system at **twice the size**. Rule pitch
**52px** (`PITCH` in `og-card.tsx`), eyebrow 18px mono, nameplate 68–80px display
800, ledger rows 23px mono, page padding `48px 52px` (hence `Nameplate`'s
`maxWidth: 1096`). 1px app rules double to 2px here.

The card's geometry is still Agate's and has not been re-derived: `PITCH` 52 was
twice Agate's 26px `--rule-pitch`, and Furniture's is **40px**. Decide deliberately
whether the card follows to 80 when it gets its colour port — do not assume 52 is
still "twice the app."

| House rule | On a card |
|---|---|
| Radius 16 / 8 / pill, one elevation | **Not ported.** The card is still zero-radius, zero-shadow. |
| Color only on signed numbers + grade letters | Same (`C.pos`/`C.neg`, `toneColor`) |
| Bricolage display + Geist Mono figures | Same, at 2× — this half IS ported |
| A panel's rows draw their own rules | Same here, and always was: explicit 2px `--rule` bottom border (Satori can't do a gradient ground) |
| `--stamp` cobalt in five sanctioned places | **None of them is a card.** Never reference stamp here. |
| Light + dark via `data-theme` | Light only |
| 👑 / 🪣 rank glyphs | Retired. Rank is a plain number; last place gets its own ink `borderTop` + dim type. |

## Fitting text: buckets, not measurement

Satori gives you no text metrics and no `text-overflow: ellipsis`. Overflow is
prevented up front, in `og-card-data.ts`: `nameplateSize()` buckets
`name.length` through `LEN_BREAKS` (`14/24/38/∞`) into a tier array
(`LARGE_TIERS` 80/68/54/44, `COMPACT_TIERS` 68/58/46/38 for the leaderboard card,
which has ledger rows eating its vertical room). Long strings also get a
`maxWidth` and wrap. A new card kind needs its own tier choice — do not
hand-pick a font size.

## Route shape

Every `opengraph-image.tsx` is the same five lines of contract:

```tsx
export const runtime = "nodejs";                    // NOT edge — lib/api uses next/headers + auth()
export const alt = "…";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";
```

then: `await loadFonts()`, a `try { card = xCard(await fetch…) } catch { card =
fallbackCard() }`, and `new ImageResponse(renderCard(card), { ...size, fonts })`.

Two things to know about that shape:

- **The try wraps ONLY the data fetch.** `loadFonts()` runs before it and
  `renderCard()` + `new ImageResponse(...)` run after it, so both are
  unprotected: a font-fetch failure or a single bad Satori style value 500s the
  route with no fallback card. That is the signature of "the page renders fine
  but the OG route 500s" — the normal page touches neither path. Check Sentry
  for the stack before guessing which one.
- **The `catch` is the normal path for crawlers, not a rare edge.** OG routes
  are exempted from the login gate by `web/middleware.ts`'s matcher
  (`.*opengraph-image`), but `lib/api` still needs a Bearer. `getBackendToken`
  **returns null** for an anonymous request instead of throwing (`web/lib/auth-server.ts:18-21`
  — the `!user` early-return precedes the `AUTH_BACKEND_SECRET` throw), so the
  backend 401s, `ApiError` is caught, and the crawler gets `fallbackCard()`.
  A cold cache (`409 cache cold`) lands in the same catch. Keep the fallback
  looking deliberate; to see a **real** card, hit the route in a browser where
  your session cookie is sent.

`renderCard()` is an if-chain over `card.kind` with the fallback frame as its
final `return` — no `default: throw`. An unknown or missing kind renders the
fallback frame rather than erroring. Preserve that: add new kinds as another
`if`, never convert it to a `switch` with a throwing default.

## Data invariants (`og-card-data.ts` is pure — test it there)

- **Never render a zero-sum swing on both sides.** `snapshot_ktc_swing` is one
  margin; printing it in both columns double-counts it. The trade card uses
  `realizedTotals(side.breakdown)` from `lib/trade-lens.ts` — the same helper
  the trade page's "Total realized" row uses, so card and page always agree.
- **Read verdicts, never recompute them.** Badge, note, and winning column come
  straight off `winners_by_lens` / `margins_by_lens` / `call` / `lens_tally` /
  `lopsidedness`. `winnerCol` is `null` for a split or undecided call — the card
  never invents a single winner.
- **Omit, don't invent.** Absent `franchise_rating` → `rating: null` and the
  block disappears; absent `track_record` → footer falls back to the real trade
  count.
- Card mappers return plain data with **no JSX**, so `web/tests/og-card-data.test.ts`
  can assert them without Satori in the loop. Keep new mappers pure.

## Verifying a change

```bash
cd web && npx vitest --config tests/vitest.config.ts run   # mappers, fonts, style tree
cd web && npx playwright test --config e2e/playwright.config.ts og.spec.ts  # real Satori
cd web && npm run build                                    # catches the route contract
```

Three layers cover this, and only the third runs Satori:

- `tests/og-card-data.test.ts` — the pure mappers.
- `tests/og-font.test.ts` — `REGISTERED_FONTS` covers every pair `og-card.tsx`
  sets; `geistMonoUrl` matches the pinned literal.
- `tests/og-card-render.test.tsx` — walks the **rendered element tree** for every
  card kind with hostile content (38-char name, empty string, ±5-digit figures)
  and fails on an `undefined` style value, any `display: grid`/`grid*` key, or a
  `var(--token)`. Fast and deterministic, but it does not prove the card renders.
- `e2e/og.spec.ts` — fetches all four `opengraph-image` routes and asserts a real
  PNG (magic bytes, >5KB). This is **the only thing that executes Satori**:
  fonts over the wire, layout, and `ImageResponse`'s streaming PNG encode. It uses
  a nonexistent league id so it needs no warmed data — the route falls to
  `fallbackCard()` and the whole pipeline still runs. Verified to go red on a bad
  `GEIST_VERSION`. Set `E2E_LEAGUE_ID` to also render real-data cards.

`next build` type-checks the routes but never executes them (no
`generateStaticParams`, so no prerender). A renderer edit that only typechecks is
**not** verified — run the e2e.

For a **visual** change (spacing, hierarchy, a new card kind) the automated
layers still can't help: they prove it renders, not that it looks right. `Cell`
clips silently, so hit the route on `make dev-web` while signed in and look at
the PNG with worst-case content.

## Common mistakes

| Mistake | What happens |
|---|---|
| `style={{ x: cond ? v : undefined }}` | Whole render throws |
| `display: "grid"` / `gridTemplateColumns` | Misrenders or throws; columns collapse |
| `fs.readFile` a font from `node_modules` | Works locally, 500s in the standalone Docker image |
| WOFF2 font URL | Satori rejects it |
| `var(--ink)` in a card style | Resolves to nothing — type/rule disappears |
| `runtime = "edge"` | `lib/api`'s `auth()` / `next/headers` break |
| Bumping `geist` in `package.json` only | Silently serves the previous version's TTF |
| A font URL that 404s | HTML body handed to Satori as font bytes; opaque parser throw, every card 500s |
| A `fontWeight` that `loadFonts()` never registered | Silent substitution — wrong face, no error |
| Assuming the route's `catch` covers everything | It wraps only the fetch; fonts and `ImageResponse` 500 uncaught |
| Trusting a green `next build` or vitest for a layout change | Neither invokes Satori; run `e2e/og.spec.ts`. Clipping is still silent — look at the PNG |
