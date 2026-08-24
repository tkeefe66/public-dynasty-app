import { test, expect } from "@playwright/test";

/**
 * The only thing in this repo that actually executes Satori (followup C14).
 *
 * vitest covers the pure mappers (`og-card-data.test.ts`), font registration
 * (`og-font.test.ts`), and the rendered style tree (`og-card-render.test.tsx`),
 * but none of them run Satori. `next build` type-checks the four
 * `opengraph-image.tsx` routes without ever executing them — there is no
 * `generateStaticParams`, so nothing prerenders. That left a real gap: a card
 * could 500 in production with every suite green.
 *
 * These specs close it by fetching the routes for real, which exercises the
 * whole chain the unit tests cannot:
 *   - `loadFonts()` — two live network fetches, WOFF2-vs-TTF, the pinned
 *     jsdelivr path for Geist Mono
 *   - Satori's own layout and style parsing
 *   - `ImageResponse` PNG encoding (which streams, so a throw inside it
 *     surfaces here and NOT in a try/catch around the constructor)
 *
 * A nonexistent league id is deliberate and sufficient: the route's data fetch
 * fails, `fallbackCard()` is used, and every one of the above still runs. That
 * makes this test hermetic — no warmed league, no fixture data, no env var —
 * while still covering the failure mode that matters. Real-data cards are
 * covered by the opt-in block at the bottom.
 */

const NO_SUCH_LEAGUE = "0";
const PNG_MAGIC = Buffer.from([0x89, 0x50, 0x4e, 0x47]); // \x89PNG

const ROUTES: [string, string][] = [
  ["league", `/league/${NO_SUCH_LEAGUE}/opengraph-image`],
  ["leaderboard", `/league/${NO_SUCH_LEAGUE}/gm/opengraph-image`],
  ["owner", `/league/${NO_SUCH_LEAGUE}/owner/u1/opengraph-image`],
  ["trade", `/league/${NO_SUCH_LEAGUE}/trade/t1/opengraph-image`],
];

for (const [name, path] of ROUTES) {
  test(`${name} OG route renders a real PNG through Satori`, async ({ request }) => {
    // Fonts are fetched on first render and memoized for the process lifetime,
    // so the first of these can be slow on a cold dev server.
    const res = await request.get(path, { timeout: 60_000 });

    expect(
      res.status(),
      `${path} did not return 200 — a font fetch, a Satori style value, or ` +
        `ImageResponse threw. The route's try/catch only wraps the data fetch, ` +
        `so check the dev server output for the stack.`,
    ).toBe(200);
    expect(res.headers()["content-type"]).toContain("image/png");

    const body = await res.body();
    expect(body.subarray(0, 4), "response is not a PNG").toEqual(PNG_MAGIC);
    // A 1200x630 card with type on it is tens of KB. A few hundred bytes means
    // an empty or all-white canvas, which is a silent-failure shape.
    expect(body.byteLength).toBeGreaterThan(5_000);
  });
}

// Opt-in: the fallback path above proves the pipeline works, but only a warmed
// league renders the real mappers' output through Satori — which is where a
// long owner name or a five-digit figure would actually clip.
//
// This takes the league from the shared gate (which resolves `.env.local`'s
// LEAGUE_ID), so it runs by default instead of waiting on an env var nobody
// sets — that silence is what let these two sit skipped indefinitely. It does
// NOT call `requireLeague()`: unlike the other data-backed specs, the block
// ABOVE this one is deliberately hermetic and must run with no league at all,
// so a missing league here narrows coverage rather than invalidating the file.
import { LEAGUE_ID } from "./gate";

test.describe("real-data cards", () => {
  test.skip(
    !LEAGUE_ID,
    "No league resolved (LEAGUE_ID / E2E_LEAGUE_ID) — real cards not rendered through Satori.",
  );

  test("league card renders with real league data", async ({ request }) => {
    const res = await request.get(`/league/${LEAGUE_ID}/opengraph-image`, {
      timeout: 60_000,
    });
    expect(res.status()).toBe(200);
    const body = await res.body();
    expect(body.subarray(0, 4)).toEqual(PNG_MAGIC);
    expect(body.byteLength).toBeGreaterThan(5_000);
  });

  test("leaderboard card renders with real league data", async ({ request }) => {
    const res = await request.get(`/league/${LEAGUE_ID}/gm/opengraph-image`, {
      timeout: 60_000,
    });
    expect(res.status()).toBe(200);
    const body = await res.body();
    expect(body.subarray(0, 4)).toEqual(PNG_MAGIC);
    expect(body.byteLength).toBeGreaterThan(5_000);
  });
});
