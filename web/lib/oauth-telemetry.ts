import type { ErrorEvent } from "@sentry/nextjs";

function decoded(value: string): string {
  for (let i = 0; i < 8; i++) {
    let next: string;
    try {
      next = decodeURIComponent(value);
    } catch {
      // Credential routes are ASCII. An unrelated malformed escape or UTF-8
      // sequence must not hide valid encoded separators or route characters.
      next = value.replace(/%[0-7][\da-f]/gi, (escape) => String.fromCharCode(parseInt(escape.slice(1), 16)));
    }
    if (next === value) break;
    value = next;
  }
  return value;
}

export function redactSharePath(value: string): string {
  const text = decoded(value);
  if (!/\/(?:api\/public|share)\/analyst\//i.test(text)) return value;
  return text.replace(/(\/(?:api\/public|share)\/analyst\/)[^/?\s"'<>]+([^?\s"'<>]*)(?:\?[^\s"'<>]*)?/gi, '$1[redacted]$2');
}

function redactPrivate(value: unknown): unknown {
  if (typeof value === 'string') return redactSharePath(value);
  if (Array.isArray(value)) return value.map(redactPrivate);
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, redactPrivate(item)]));
  return value;
}

function isOAuth(value: unknown): boolean {
  const text = decoded(JSON.stringify(value ?? "")).toLowerCase();
  return ["api.login.yahoo.com", "/api/me/yahoo", "/api/auth/callback/yahoo", "/api/yahoo/connect", "/api/public/analyst/", "/share/analyst/"].some((part) => text.includes(part));
}

export function redactOAuthEvent(event: ErrorEvent): ErrorEvent | null {
  if (isOAuth(event.request?.url)) return null;
  if (event.breadcrumbs) event.breadcrumbs = event.breadcrumbs.filter((crumb) => !isOAuth(crumb));
  return redactPrivate(event) as ErrorEvent;
}
