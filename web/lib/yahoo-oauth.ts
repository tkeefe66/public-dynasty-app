/** Only use configured origin for redirects/CSRF, never untrusted Host headers. */
export function appOrigin(): string {
  const configured = process.env.AUTH_URL || process.env.NEXTAUTH_URL;
  if (configured) return new URL(configured).origin;
  if (process.env.CANONICAL_HOST) return `https://${process.env.CANONICAL_HOST}`;
  if (process.env.NODE_ENV !== "production") return "http://localhost:3000";
  throw new Error("App origin is not configured");
}

export function sameOrigin(request: Request): boolean {
  return request.headers.get("origin") === appOrigin();
}

export const YAHOO_STATE_COOKIE = "yahoo-link-state";
