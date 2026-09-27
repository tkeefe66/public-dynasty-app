import type { ErrorEvent } from "@sentry/nextjs";

function isOAuth(value: unknown): boolean {
  const text = JSON.stringify(value ?? "").toLowerCase();
  return ["api.login.yahoo.com", "/api/me/yahoo", "/api/auth/callback/yahoo", "/api/yahoo/connect"].some((part) => text.includes(part));
}

export function redactOAuthEvent(event: ErrorEvent): ErrorEvent | null {
  if (isOAuth(event.request?.url)) return null;
  if (event.breadcrumbs) event.breadcrumbs = event.breadcrumbs.filter((crumb) => !isOAuth(crumb));
  return event;
}
