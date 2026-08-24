/**
 * Forge a NextAuth session cookie for the e2e suite (followup C6).
 *
 * `web/middleware.ts` gates every page behind Google OAuth, so Playwright could
 * only ever test the landing→login redirect. Rather than ship a test bypass —
 * an env-gated Credentials provider, or a secret-header escape in middleware,
 * both of which put a live bypass code path in production — this mints the
 * cookie the app already trusts.
 *
 * NextAuth v5 sessions here are JWT-strategy cookies encrypted (JWE) with
 * `AUTH_SECRET`. Anyone holding `AUTH_SECRET` can mint one; that is already the
 * trust model, so forging one in tests adds no attack surface. The app ships
 * ZERO code for this: everything here lives under `e2e/`, and the web→api proxy
 * mints its backend HS256 token from the forged session server-side exactly as
 * it does in production.
 *
 * SECURITY: the test environment MUST use a throwaway `AUTH_SECRET`, never the
 * production value. See `e2e/README.md`.
 */
import { encode } from "@auth/core/jwt";

/** The synthetic user every authed spec runs as. */
export const E2E_USER = {
  /** Becomes the JWT `sub`, which the backend upserts as the user's google_sub. */
  sub: "e2e-test-subject",
  email: "e2e@test.local",
  name: "E2E Tester",
} as const;

/**
 * Auth.js derives the JWE encryption key from `AUTH_SECRET` **and a salt**, and
 * the salt is the session cookie's own name — so the name and the salt must
 * agree or the app decrypts nothing. The `__Secure-` prefix applies only on
 * https origins, which is why this is derived from the base URL rather than
 * hardcoded.
 */
export function sessionCookieName(baseURL: string): string {
  return baseURL.startsWith("https://")
    ? "__Secure-authjs.session-token"
    : "authjs.session-token";
}

export interface ForgedCookie {
  name: string;
  value: string;
  domain: string;
  path: string;
  httpOnly: boolean;
  secure: boolean;
  sameSite: "Lax";
  expires: number;
}

/**
 * Mint the session cookie Playwright should carry.
 *
 * Throws when `AUTH_SECRET` is absent — callers decide whether that's a skip or
 * a failure, but it is never silently ignored, because a missing secret would
 * otherwise look like a mysterious redirect to /login.
 */
export async function forgeSessionCookie(opts: {
  baseURL: string;
  /** Seconds until the forged session expires. One hour is plenty for a run. */
  maxAge?: number;
}): Promise<ForgedCookie> {
  const secret = process.env.AUTH_SECRET;
  if (!secret) {
    throw new Error(
      "AUTH_SECRET is not set — the e2e session cookie can't be minted. " +
        "Set a THROWAWAY value (never the production secret) in web/.env.local " +
        "or the CI environment. See web/e2e/README.md.",
    );
  }

  const url = new URL(opts.baseURL);
  const name = sessionCookieName(opts.baseURL);
  const maxAge = opts.maxAge ?? 60 * 60;

  const value = await encode({
    // salt === cookie name; see sessionCookieName above.
    salt: name,
    secret,
    maxAge,
    token: {
      sub: E2E_USER.sub,
      email: E2E_USER.email,
      name: E2E_USER.name,
    },
  });

  return {
    name,
    value,
    domain: url.hostname,
    path: "/",
    httpOnly: true,
    secure: url.protocol === "https:",
    sameSite: "Lax",
    expires: Math.floor(Date.now() / 1000) + maxAge,
  };
}
