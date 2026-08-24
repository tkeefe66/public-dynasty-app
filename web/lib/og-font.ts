// Google Fonts serves a TTF src when the request UA is not woff2-capable.
// Satori (next/og) needs TTF/OTF/WOFF, not WOFF2. We fetch once and cache.
//
// Share cards use the same two faces the app itself uses (web/app/layout.tsx):
// Bricolage Grotesque for nameplates/headlines and Geist Mono for the eyebrow +
// ruled rows. Bricolage replaced Archivo when the design system shipped
// (.design/tokens/typography.css); the standalone Inter this card started on has
// been gone for two systems.
//
// ---------------------------------------------------------------------------
// WHY THIS DOES NOT READ .design/assets/fonts/ — two independent blockers, and
// each one alone is fatal:
//
//   1. Format. All six design-system builds are WOFF2 (magic bytes `wOF2`).
//      The opentype parser bundled inside next/og recognises `wOFF` and bare
//      TTF/OTF; it has no WOFF2 decoder (`grep -c woff2` over
//      node_modules/next/dist/compiled/@vercel/og/index.node.js is 0). Satori
//      rejects the bytes.
//   2. Reachability. `web/next.config.mjs` builds `output: "standalone"`, which
//      prunes to what Next's build-time import tracing can see. A runtime
//      `fs.readFile` of a binary asset with no accompanying `import` is exactly
//      the reference shape tracing misses: it works locally and 500s in the
//      Railway image. That was tried and rejected once already.
//
// So the card gets the same FACE from Google Fonts' static TTF instances, which
// needs no tracing and no decoder. Two consequences worth knowing:
//
//   - The card renders static 700/800 cuts, while the app renders the variable
//      build. Bricolage's `opsz` axis therefore does not follow the card's 68-88px
//      nameplates — they draw at the static instance's fixed optical size. Fixing
//      that means decompressing the woff2 to a TTF at build time and committing
//      the result, which puts font binaries outside `.design/`.
//   - The weight ceiling is 800, not Archivo's 900. `--weight-display` is 800,
//      so the nameplates are on-system; they are one step lighter than before.
//
// Geist Mono is NOT on Google Fonts — the app gets it from the `geist` npm
// package (web/node_modules/geist) — so its TTFs come from jsdelivr's npm mirror
// instead of local disk, for the same tracing reason.
const GEIST_VERSION = "1.3.1"; // keep in sync with package.json's "geist" dependency

/** The display family, spelled for a Google Fonts `family=` query and for
 *  Satori's `fontFamily` matching. Both spellings must stay in step with the
 *  `fontFamily: "..."` strings in og-card.tsx — `tests/og-font.test.ts` proves
 *  they do. */
export const DISPLAY_FAMILY = "Bricolage Grotesque";
const DISPLAY_QUERY = "Bricolage+Grotesque";

export function extractFontUrl(css: string): string | null {
  const m = css.match(/src:\s*url\((https:\/\/[^)]+\.ttf)\)\s*format\('truetype'\)/);
  return m ? m[1] : null;
}

/** jsdelivr serves npm package contents verbatim — the exact TTF the `geist`
 *  package ships, pinned to the installed version. */
export function geistMonoUrl(weightName: "Regular" | "Bold"): string {
  return `https://cdn.jsdelivr.net/npm/geist@${GEIST_VERSION}/dist/fonts/geist-mono/GeistMono-${weightName}.ttf`;
}

/** A failed fetch must not become font bytes: without this, a 404 or an outage
 *  page hands Satori HTML to parse and the error surfaces as an unreadable
 *  font-parsing crash instead of "the CDN is down". */
async function fetchBytes(url: string, what: string): Promise<ArrayBuffer> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${what}: ${r.status} from ${url}`);
  return r.arrayBuffer();
}

async function fetchGoogleFont(query: string, weight: number, what: string): Promise<ArrayBuffer> {
  const res = await fetch(
    `https://fonts.googleapis.com/css2?family=${query}:wght@${weight}`,
    { headers: { "User-Agent": "Mozilla/5.0 (compatible; satori)" } },
  );
  if (!res.ok) throw new Error(`${what} ${weight} css: ${res.status}`);
  const url = extractFontUrl(await res.text());
  if (!url) throw new Error(`no ttf for ${what} ${weight}`);
  return fetchBytes(url, `${what} ${weight}`);
}

async function fetchGeistMono(weightName: "Regular" | "Bold"): Promise<ArrayBuffer> {
  return fetchBytes(geistMonoUrl(weightName), `Geist Mono ${weightName}`);
}

export interface OgFont { name: string; data: ArrayBuffer; weight: 400 | 700 | 800; style: "normal"; }

/** Every family/weight pair the cards may use. Satori substitutes an
 *  unregistered pair silently, so `tests/og-font.test.ts` asserts this list
 *  covers every pair `og-card.tsx` actually sets. */
export const REGISTERED_FONTS: { name: string; weight: 400 | 700 | 800 }[] = [
  { name: DISPLAY_FAMILY, weight: 800 },
  { name: DISPLAY_FAMILY, weight: 700 },
  { name: "Geist Mono", weight: 400 },
  { name: "Geist Mono", weight: 700 },
];

let cached: OgFont[] | null = null;

/** Bricolage 800 (`--weight-display`: nameplates, verdict headlines) +
 *  Bricolage 700 (`--weight-heading`: franchise names on the league and
 *  leaderboard cards, mirroring the app's `font-display font-bold`) + Geist Mono
 *  400/700 (eyebrow, ruled rows, emphasis) — fetched once and memoized for the
 *  process lifetime.
 *
 *  Every weight `og-card.tsx` sets must be registered here. Satori substitutes
 *  an unregistered family/weight pair **silently**, so a missing weight is not
 *  an error — it is a card that quietly renders in the wrong face. The display
 *  face's 700 was missing for exactly that reason once (found by the
 *  og-card-satori-gotchas audit): three call sites asked for it and got 900. */
export async function loadFonts(): Promise<OgFont[]> {
  if (cached) return cached;
  const [display800, display700, monoRegular, monoBold] = await Promise.all([
    fetchGoogleFont(DISPLAY_QUERY, 800, DISPLAY_FAMILY),
    fetchGoogleFont(DISPLAY_QUERY, 700, DISPLAY_FAMILY),
    fetchGeistMono("Regular"),
    fetchGeistMono("Bold"),
  ]);
  cached = [
    { name: DISPLAY_FAMILY, data: display800, weight: 800, style: "normal" },
    { name: DISPLAY_FAMILY, data: display700, weight: 700, style: "normal" },
    { name: "Geist Mono", data: monoRegular, weight: 400, style: "normal" },
    { name: "Geist Mono", data: monoBold, weight: 700, style: "normal" },
  ];
  return cached;
}
