---
name: design-system-sync
description: Use when installing or re-syncing the generated `.design/` design system, or editing `web/app/globals.css`'s token imports, `web/tailwind.config.ts`'s fontFamily/theme maps, `next/font` setup in `web/app/layout.tsx`, or `web/Dockerfile`'s copy layout. Also use when a `var(--token)` resolves to nothing, a font silently falls back to system-ui, a design value looks hardcoded in `web/`, or a Docker build fails on a `../../.design` import that works locally.
---

# Syncing `.design/` into web/

`.design/` is **generated** and is the source of truth for every design value. The
app **imports** it; it never copies it. A literal colour, size, weight or duration
anywhere in `web/` is drift by definition — it cannot be changed from the place
that owns it. See `DESIGN_SYSTEM.md`: a `.design/` change merged without design-
project review is drift too.

## The import contract

`web/app/globals.css` imports exactly five files, fonts first (so `@font-face`
precedes anything resolving a family), and declares **no values of its own**:

```css
@import "../../.design/tokens/fonts.css";
@import "../../.design/tokens/colors.css";
@import "../../.design/tokens/typography.css";
@import "../../.design/tokens/rhythm.css";
@import "../../.design/tokens/stamp.css";

@tailwind base;
@tailwind components;
@tailwind utilities;
```

Two token files are deliberately **not** imported:

| File | Why not |
|---|---|
| `tokens/base.css` | The design system's own element reset. Tailwind preflight owns that here; importing both fights. |
| `tokens/legacy-agate.css` | A snapshot of the retired predecessor, scoped to `:root[data-theme="agate"]` for the four Agate kits inside `.design/` itself. Nothing in this app asks for that scope. |

Dark ground needs no adapter: the tokens key on `:root[data-theme="dark"]`, which
is the attribute `components/ThemeProvider.tsx` writes to `documentElement`.

## After every re-sync: prove no token dangles

A renamed or dropped token fails **silently** — `var(--gone)` resolves to nothing
and the element renders unstyled rather than erroring. Run the coverage diff:

```bash
cd web && grep -rhoE "var\(--[a-z0-9-]+" app components lib tailwind.config.ts \
  | sed 's/var(--//' | sort -u > /tmp/used.txt
cd ../.design/tokens && grep -hoE "^[[:space:]]*--[a-z0-9-]+" \
  colors.css typography.css rhythm.css stamp.css fonts.css \
  | tr -d ' ' | sed 's/^--//' | sort -u > /tmp/provided.txt
comm -23 /tmp/used.txt /tmp/provided.txt
```

Expected output is **exactly** the `next/font` variables, which are not design
tokens: `font-geist-sans`, `font-geist-mono`, `font-bricolage`. Anything else is
either a token the sync dropped (fix upstream in `.design/`, never locally) or a
local value someone re-added. Use `-E` with `[[:space:]]`, not `\s` — BSD grep
does not support `\s` and the second list comes back empty, which reads as "every
token is missing."

## Three traps that break the build, not the styling

**1. The Docker context copies one subdirectory.** Both Railway services build
from the **repo root**, but `web/Dockerfile` used to `COPY web ./` into `/app` —
so `../../.design` did not exist in the image and every build died on the CSS
import while `npm run build` passed locally. The image must reproduce the repo's
directory *relationship*:

```dockerfile
WORKDIR /repo
COPY --from=deps /app/node_modules ./web/node_modules
COPY web ./web
COPY .design ./.design
WORKDIR /repo/web
```

Next infers its file-tracing root from the nearest lockfile (`web/package-lock.json`),
so standalone output keeps `server.js` at the top and the runner stage only needs
its paths repointed at `/repo/web`. Font binaries reach the browser through
`.next/static/media` — webpack emits them — so **nothing reads `.design` at
runtime**.

**2. `next/font/local`'s `src` entries carry no `unicode-range`.** Listing both a
`latin` and a `latin-ext` build declares two `@font-face` rules with identical
descriptors, and the later one wins outright — including for basic latin, which
that file does not cover. List **only the latin build**, then chain to the real
family name behind the variable so `.design/tokens/fonts.css` (which declares both
builds *with* their ranges) supplies the accented glyphs:

```ts
display: ["var(--font-bricolage)", "Bricolage Grotesque"],
```

An SVG `fontFamily` attribute cannot use a Tailwind class, so it spells the same
stack out — keep `ProductionTimeline.tsx`'s `DISPLAY` in step with the config.

**3. Satori cannot read these font files at all.** All six builds are woff2
(`wOF2`), and next/og's bundled parser has no woff2 decoder. OG cards fetch static
TTF over HTTP instead. **REQUIRED BACKGROUND:** `og-card-satori-gotchas`.

Use the **variable** builds in the app regardless: Bricolage's `opsz` axis redraws
letterforms for the size they are set at, and the scale runs 8.5px to 44px, so a
static instance would freeze every nameplate at a 14px cut. `font-weight: 200 800`
is a range — never add a second face for another weight of the same family.

## The shipped package has four defects — do not trust it blindly

Verified 2026-08-14 against `.design/` as installed. Re-check on each sync; these
are upstream bugs to report, not things to patch locally.

| Defect | Consequence |
|---|---|
| `guidelines/DESIGN.md` still describes **Agate** — its frontmatter says `#f7f6f1`, Archivo, 26px, `rounded: 0` | Authoring from it re-encodes the retired system. `SKILL.md`'s own rule list wins; its §9 "Still open" is what makes people think `og-font.ts` loads Inter. |
| `guidelines/layer1-handoff.html` **does not exist**, though `SKILL.md` cites it twice as the record of what changed and why | There is no changed-rules document. `readme.md`'s top banner (lines 3–17) is the closest thing. |
| **`ui_kits/` does not exist**, though `readme.md` and `SKILL.md` cite it repeatedly — "~40 real product screens", "17 in `ui_kits/furniture/`", "`phones.html` is the contact sheet", and `ui_kits/furniture/icons.js` as the icon source | Every drawn-screen reference is dead. The nineteen marks actually live in `components/controls/fx-icon-paths.js`. This one costs a whole agent run if you brief against the cited path. |
| `components/data/Bar.jsx` hardcodes `borderRadius: 3` (four places) | A **fourth radius** on a system whose own rule is 16 / 8 / pill, "no fourth". It hides because `Bar`'s default height is 5px, where CSS overlapping-curve clamping reduces both `3` and `--radius-pill` to the same 2.5px — so at the shipped size it is invisibly wrong. It diverges only at height ≥ 7. **Do not port it verbatim**: `rounded-[3px]` fails the drift guard, and the inline-style form the source uses is worse — a `style={{ borderRadius }}` is invisible to a `rounded-*` regex, so it would smuggle an unenforceable radius into a scoped file with the guard green. `web/components/furniture/Bar.tsx` uses `rounded-pill`, which renders identically at every reachable geometry. |
| `components/data/WindowCell.prompt.md` contradicts what this app draws | Not a package bug — a spec the app violates, recorded here because it is easy to miss. It says of the competitive window: *"Do not draw it as a quadrant or a scatter plot: that makes an ordered position look like a coordinate, and it was the diagram users could not read."* The Outlook tab's `Field` (`web/components/ownerdeepdive/WindowSection.tsx`) is exactly that quadrant. `WindowCell` — an ordered five-step ladder — is the sanctioned drawing. |
| `tokens/fonts.css` ends with a Google Fonts `@import` for Archivo, for its own legacy scope | It lands in our bundle after real rules, so browsers ignore it and Archivo is never fetched — inert, but a dead line. It belongs in `legacy-agate.css`. **Verified empirically 2026-08-14**: the `@import` *is* present in the shipped production stylesheet, and a real page load makes **zero** requests to `fonts.googleapis.com`. Grepping the CSS looks alarming and proves nothing — check the network panel before reporting this as a live third-party fetch or a privacy leak. |

`readme.md` is Agate-bodied with a Furniture banner: its **component tables**
(the 22 primitives) and **iconography** section are current; VISUAL FOUNDATIONS
is not.

## The guard widens, it does not start wide

`web/tests/furniture-rules.test.ts` runs at full strength over `SCOPED_DIRS` only,
which starts empty. Add a directory the moment it is converted; the port is done
when `UNSCOPED` is empty. Landing the guard wide against an unported codebase
makes CI red for the whole migration, which ends with someone deleting the guard.
**REQUIRED BACKGROUND:** `shrinking-lint-baseline`.

## Verifying a sync

```bash
cd web && npm run build && npx tsc --noEmit
cd web && npx vitest --config tests/vitest.config.ts run
```

Then confirm the values actually reached the browser — a successful build proves
the imports resolved, not that the right tokens won:

```bash
grep -o "rule-pitch:40px\|2f42ff" web/.next/static/css/*.css   # Furniture landed
grep -o "f7f6f1\|rule-pitch:26px" web/.next/static/css/*.css   # must be empty
```

`e2e/*.spec.ts` reuses whatever is on the configured port (`reuseExistingServer`)
and does **not** check that the listener is this app — so another project's dev
server means you test **its** pages and misread the result. This is not
hypothetical: it happened on 2026-08-14, and the symptom was not "wrong app" but
the auth setup failing with `forged session was rejected by middleware` (the other
app has no idea what our cookie is). The only tell was an unfamiliar font name in
the failure log's `<html class>`.

`e2e/playwright.config.ts` now threads **`E2E_PORT`** through both the dev command
and the base URL, so moving off a busy port is one env var:

```bash
E2E_PORT=3210 E2E_LEAGUE_ID=... npx playwright test \
  --config e2e/playwright.config.ts --project=chromium-authed --grep viewport
```

Still worth `curl -s localhost:$PORT | grep '<title>'` before trusting a run.
