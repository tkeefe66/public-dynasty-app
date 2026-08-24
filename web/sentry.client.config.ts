import * as Sentry from "@sentry/nextjs";

// Inert unless NEXT_PUBLIC_SENTRY_DSN is set (must be public to reach the browser).
Sentry.init({
  dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,
  enabled: !!process.env.NEXT_PUBLIC_SENTRY_DSN,
  tracesSampleRate: 0,
});
