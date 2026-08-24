import "server-only";
import { SignJWT } from "jose";

/**
 * !! SESSIONLESS BACKEND TOKEN — FOR OG CARD IMAGES ONLY. !!
 *
 * WHY IT EXISTS
 * The four `opengraph-image.tsx` routes under `app/league/` render the share
 * cards that Slack / iMessage / Twitter unfurl. Those crawlers carry no
 * session, and Next's metadata routes get no session even for a signed-in
 * visitor (`auth()` yields no user there). `getBackendToken()` therefore
 * returns null, the backend 401s, and every shared link unfurled as the generic
 * fallback frame. This mints a token that does not need a user.
 *
 * WHAT IT DELIBERATELY EXPOSES
 * It makes the data printed on those four cards readable without a session.
 * That is inherent and accepted: a crawler has no session, so there is no
 * version of "real unfurls" that is session-gated. The token itself never
 * leaves the Next.js server — it is minted per render, inside the image route,
 * and only ever travels to the backend.
 *
 * HOW THE BLAST RADIUS IS BOUNDED (backend side, `api/app/auth/deps.py`)
 *   - The token carries `scope: "og-card"` and NO identity claims — no `sub`,
 *     no `email`, no name. There is no user for it to impersonate.
 *   - `get_current_user` rejects it (401), so it can never reach
 *     `users.upsert_from_token` or `users.touch_activity`. Card traffic cannot
 *     create a user row and cannot inflate the active-days metric. That also
 *     closes `/api/me`, `/api/events`, `/api/admin` and the bets handlers.
 *   - `require_league_member` admits it only for GET/HEAD on exactly the four
 *     card read endpoints. Writes are impossible; every other league route
 *     (including `/refresh`) 401s.
 *
 * WHAT MUST NEVER CALL THIS
 *   - `lib/api.ts`'s `registerServerAuth` provider (RSC page fetches).
 *   - `app/api/[...path]/route.ts` — the browser-facing proxy. Wiring it there
 *     would hand every anonymous visitor a backend credential.
 *   - Any client component, any mutation, any route that is not an
 *     `opengraph-image` route.
 * Its only legitimate caller is `lib/og-api.ts`, which is GET-only and hits
 * only the four allowlisted paths.
 */
export async function getOgCardToken(): Promise<string> {
  const secretStr = process.env.AUTH_BACKEND_SECRET;
  if (!secretStr) {
    throw new Error("AUTH_BACKEND_SECRET is not set");
  }
  const secret = new TextEncoder().encode(secretStr);

  // No subject and no email: this is a scope, not an identity. Short TTL — the
  // token is minted and spent inside a single image render.
  return await new SignJWT({ scope: "og-card" })
    .setProtectedHeader({ alg: "HS256" })
    .setIssuedAt()
    .setExpirationTime("2m")
    .sign(secret);
}
