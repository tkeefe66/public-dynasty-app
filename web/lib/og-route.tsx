import { ImageResponse } from "next/og";
import { fallbackCard, type AnyCard } from "./og-card-data";
import { renderCard } from "./og-card";
import { loadFonts } from "./og-font";
import { BLANK_CARD_PNG_B64 } from "./og-blank";

export const OG_SIZE = { width: 1200, height: 630 } as const;

/**
 * The shared body of all four `opengraph-image.tsx` routes.
 *
 * WHY THIS EXISTS. Every route was written the same way:
 *
 * ```ts
 * const fonts = await loadFonts();          // <- outside the try
 * try { card = build(); } catch { card = fallbackCard(); }
 * return new ImageResponse(renderCard(card), { ...size, fonts });   // <- outside the try
 * ```
 *
 * The `try` wrapped ONLY the data fetch, so the two things most likely to throw
 * were unprotected: `loadFonts()` makes four live network calls on a cold start
 * (Google Fonts + jsdelivr), and Satori throws on a single `undefined` style
 * value. Either one 500s the route with no card at all — and neither is visible
 * from the normal page, which touches neither path. That is the exact signature
 * of "the page renders fine but the OG route 500s".
 *
 * WHAT THIS CAN AND CANNOT CATCH. Read this before trusting it:
 *
 *   - font fetch fails      -> caught, serves the blank card below
 *   - data fetch fails      -> caught, serves `fallbackCard()` (the normal path
 *                              for a crawler: no session, so the backend 401s)
 *   - Satori layout throws  -> caught, RETRIED on `fallbackCard()`, which is the
 *                              simplest tree in the system, then the blank card
 *   - PNG **encode** throws -> NOT caught. `ImageResponse` streams its body, so
 *                              a failure during encoding happens after this
 *                              function has returned. Nothing here can wrap it.
 *
 * That last line is why this is an improvement and not a guarantee.
 */
export async function ogImage(build: () => Promise<AnyCard>): Promise<Response> {
  let fonts: Awaited<ReturnType<typeof loadFonts>>;
  try {
    fonts = await loadFonts();
  } catch {
    // No fonts means Satori cannot draw anything at all — every text node needs
    // a registered face. A branded blank beats a 500: the unfurl still shows a
    // card-shaped image instead of a broken-link box.
    return blankCard();
  }

  const faces = fonts.map((f) => ({ name: f.name, data: f.data, weight: f.weight, style: f.style }));

  let card: AnyCard;
  try {
    card = await build();
  } catch {
    card = fallbackCard();
  }

  try {
    return new ImageResponse(renderCard(card), { ...OG_SIZE, fonts: faces });
  } catch {
    // The card's own tree is bad — a new kind with an `undefined` style value is
    // the usual cause. `fallbackCard()` is a different, much simpler tree, so it
    // is worth one retry rather than going straight to blank.
    try {
      return new ImageResponse(renderCard(fallbackCard()), { ...OG_SIZE, fonts: faces });
    } catch {
      return blankCard();
    }
  }
}


function blankCard(): Response {
  return new Response(Buffer.from(BLANK_CARD_PNG_B64, "base64"), {
    headers: {
      "content-type": "image/png",
      // Short cache: this is a degraded response, and the next crawl should get
      // a real card once the font CDN or the bad style is fixed.
      "cache-control": "public, max-age=60",
    },
  });
}
