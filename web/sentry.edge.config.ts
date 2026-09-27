import * as Sentry from "@sentry/nextjs";
import { redactOAuthEvent } from "@/lib/oauth-telemetry";

// Inert unless SENTRY_DSN is set.
Sentry.init({
  dsn: process.env.SENTRY_DSN,
  enabled: !!process.env.SENTRY_DSN,
  tracesSampleRate: 0,
  beforeSend: redactOAuthEvent,
});
