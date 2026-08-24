import "server-only";
import { cache } from "react";
import { SignJWT } from "jose";
import { auth } from "@/auth";
import { registerServerAuth } from "@/lib/api";

/**
 * Mint a short-lived backend-facing HS256 token for the current session.
 *
 * Signed with AUTH_BACKEND_SECRET, which the FastAPI backend verifies
 * (TRADE_GRADER_AUTH_BACKEND_SECRET). Returns null when there is no session
 * (e.g. crawlers hitting OG-image routes) so callers can degrade gracefully.
 *
 * Wrapped in React cache(): a single RSC render with N backend fetches signs
 * one token, not N. (In a route handler there's no render scope, so it simply
 * computes each call — still correct.)
 */
export const getBackendToken = cache(async (): Promise<string | null> => {
  const session = await auth();
  const user = session?.user;
  if (!user) return null;

  const secretStr = process.env.AUTH_BACKEND_SECRET;
  if (!secretStr) {
    throw new Error("AUTH_BACKEND_SECRET is not set");
  }
  const secret = new TextEncoder().encode(secretStr);

  return await new SignJWT({
    email: user.email ?? undefined,
    name: user.name ?? undefined,
    picture: user.image ?? undefined,
  })
    .setProtectedHeader({ alg: "HS256" })
    .setSubject((user as { id?: string }).id ?? "")
    .setIssuedAt()
    .setExpirationTime("5m")
    .sign(secret);
});

// Register the server-side auth-header provider with the shared API client.
// This module is imported only from server modules (the root layout and the
// proxy route handler), so it never reaches the client bundle. Importing it for
// its side effect wires RSC fetches (which call lib/api directly against
// API_URL) to attach a fresh Bearer token.
registerServerAuth(async (): Promise<Record<string, string>> => {
  const token = await getBackendToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
});
